"""The four checkpointed steps of one job (requirements §6.1).

The pipeline owns no database code: every write goes through the callbacks in
``PipelineContext``, which the JobManager supplies. That is what keeps a write transaction
from ever spanning the yt-dlp subprocess or a call to Radarr/Sonarr (§3.1 rule 2).
"""

import asyncio
import shutil
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from typing import Any

import httpx
from tenacity import AsyncRetrying, RetryCallState, retry_if_exception_type, stop_after_attempt

from app.db.base import utcnow
from app.integrations.arr import (
    EPISODE_SCAN,
    FINISHED,
    MOVIE_SCAN,
    RADARR,
    SONARR,
    ArrAuthError,
    ArrClientError,
    ArrConnection,
    ArrError,
    ArrServerError,
    ArrTimeout,
    ImportPolicy,
    RadarrClient,
    Rejection,
    SonarrClient,
)
from app.jobs.constants import STEPS, ImportStatus, JobStatus, Step
from app.jobs.utils import SAMPLE, explain_rejection
from app.library.naming import DailyEpisode, Episode, Movie, Other, Target
from app.library.organizer import CollisionPolicy, is_organized, organize, prune_empty_dirs
from app.library.probe import ProbeError, probe
from app.transcode.profiles import TranscodeProfile, marker
from app.transcode.runner import transcode
from app.ytdlp.command import build_argv
from app.ytdlp.cookies import write_private
from app.ytdlp.runner import (
    DOWNLOAD_WAIT,
    DownloadCancelled,
    Progress,
    cleanup_partials,
    download,
    read_final_path,
)
from app.ytdlp.runtime import JsRuntime
from app.ytdlp.schemas import DownloadOptions
from app.ytdlp.stream import StreamType, resolve_auto

Checkpoint = Callable[[Step, float, dict[str, Any]], Awaitable[None]]
SetStatus = Callable[[JobStatus, Step], Awaitable[None]]

#: The import step's done-check (requirements §6.1).
IMPORT_DONE = (ImportStatus.IMPORTED, ImportStatus.NOT_IMPORTED)
#: Retried because they pass: everything else is a verdict, not a hiccup (§6.1).
IMPORT_RETRYABLE = (httpx.TransportError, ArrServerError, ArrTimeout)
BAD_KEY_HINT = "check the API key in Settings"
#: The plaintext cookies for one download; it exists only while the download step runs (§8).
COOKIES_FILE = "cookies.txt"


def not_configured(app: str) -> str:
    return f"{app} is not configured in Settings"


@dataclass
class PipelineContext:
    job_id: str
    url: str
    options: DownloadOptions
    stream_type: StreamType
    target: Target
    job_dir: Path
    completed_dir: Path
    incomplete_dir: Path
    cancel: asyncio.Event
    download_slot: asyncio.Semaphore
    transcode_slot: asyncio.Semaphore
    checkpoint: Checkpoint
    set_status: SetStatus
    on_progress: Callable[[Progress], None]
    on_log: Callable[[str], None]
    on_attempt: Callable[[int], None]
    aria2c_available: bool = False
    #: The per-profile quality resolved before the step, so no session spans ffmpeg (§3.1).
    transcode_quality: dict[str, int] = field(default_factory=dict)
    libva_driver: str = "iHD"
    js_runtime: JsRuntime | None = None
    last_completed_step: Step | None = None
    completed_path: Path | None = None
    collision_policy: CollisionPolicy = CollisionPolicy.KEEP_BOTH
    #: The import half (§7.5); an `other` target never uses it.
    import_status: str = ImportStatus.NOT_APPLICABLE
    radarr_movie_id: int | None = None
    radarr: RadarrClient | None = None
    radarr_connection: ArrConnection | None = None
    sonarr_episode_id: int | None = None
    sonarr: SonarrClient | None = None
    sonarr_connection: ArrConnection | None = None
    import_policy: ImportPolicy = field(default_factory=ImportPolicy)
    #: The site's cookie file, decrypted before the step so no session spans yt-dlp (§8).
    cookies: str | None = None
    #: Told what yt-dlp left in the cookie file after a successful download (write-back).
    on_cookies_used: Callable[[str], Awaitable[None]] | None = None
    #: Injectable so tests run the retry policy without sleeping (§6.1).
    download_wait: Any = DOWNLOAD_WAIT
    step_timings: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class ImportOutcome:
    """What the import step decided, written in one checkpoint."""

    status: ImportStatus
    command_id: str | None = None
    detail: dict[str, Any] | None = None
    path: str | None = None


async def execute(ctx: PipelineContext) -> None:
    """Run the steps after ``last_completed_step``, each behind its own done-check."""
    video_path: Path | None = None
    start = STEPS.index(ctx.last_completed_step) + 1 if ctx.last_completed_step else 0

    for step in STEPS[start:]:
        _raise_if_cancelled(ctx)
        started = perf_counter()

        if step is Step.DOWNLOAD:
            video_path = await _download_done(ctx)
            if video_path is None:
                video_path = await _download(ctx)

        elif step is Step.TRANSCODE:
            # §6.1 done-check: nothing was asked for, or the marker says it already ran.
            if ctx.options.transcode is not TranscodeProfile.OFF and not await asyncio.to_thread(
                marker(ctx.job_dir).is_file
            ):
                if video_path is None:
                    video_path = read_final_path(ctx.job_dir)
                await _transcode(ctx, video_path)
                continue

        elif step is Step.ORGANIZE:
            if video_path is None:
                video_path = read_final_path(ctx.job_dir)
            if not await asyncio.to_thread(
                is_organized, ctx.job_dir, video_path, ctx.completed_path
            ):
                await _organize(ctx, video_path)
                continue
            await ctx.checkpoint(step, perf_counter() - started, {})
            continue

        else:
            # §6.1: skip when the import already has a verdict; `other` has nothing to import.
            if not isinstance(ctx.target, Other) and ctx.import_status not in IMPORT_DONE:
                await _import(ctx)
                continue

        await ctx.checkpoint(step, perf_counter() - started, {})


def _raise_if_cancelled(ctx: PipelineContext) -> None:
    if ctx.cancel.is_set():
        raise DownloadCancelled("cancelled")


async def _download_done(ctx: PipelineContext) -> Path | None:
    """§6.1: `final_path` names a non-empty file that ffprobe can read."""
    if not (ctx.job_dir / "final_path").is_file():
        return None
    try:
        path = read_final_path(ctx.job_dir)
    except Exception:
        return None
    if not await asyncio.to_thread(_is_non_empty, path):
        return None
    try:
        await probe(path)
    except ProbeError:
        return None
    ctx.on_log(f"download already finished: {path}")
    return path


def _is_non_empty(path: Path) -> bool:
    return path.is_file() and path.stat().st_size > 0


async def _download(ctx: PipelineContext) -> Path:
    resolved = resolve_auto(ctx.stream_type, ctx.options, ctx.aria2c_available)
    cookies_path = ctx.job_dir / COOKIES_FILE if ctx.cookies is not None else None
    argv = build_argv(
        ctx.url,
        ctx.options,
        resolved,
        job_dir=ctx.job_dir,
        cookies_path=cookies_path,
        js_runtime=ctx.js_runtime,
    )
    try:
        # The download slot is held only for this step (§6.1).
        async with ctx.download_slot:
            _raise_if_cancelled(ctx)
            await ctx.set_status(JobStatus.DOWNLOADING, Step.DOWNLOAD)
            if cookies_path is not None and ctx.cookies is not None:
                await asyncio.to_thread(write_private, cookies_path, ctx.cookies)
            try:
                path = await download(
                    argv,
                    job_dir=ctx.job_dir,
                    retries=ctx.options.retries,
                    cancel=ctx.cancel,
                    on_progress=ctx.on_progress,
                    on_log=ctx.on_log,
                    on_attempt=ctx.on_attempt,
                    wait=ctx.download_wait,
                )
            except DownloadCancelled:
                raise
            except Exception:
                # Only this job's leftovers, and only inside its own dir.
                await asyncio.to_thread(cleanup_partials, ctx.job_dir)
                raise
        if cookies_path is not None and ctx.on_cookies_used is not None:
            # yt-dlp has exited, so this write spans no subprocess (§3.1 rule 2).
            refreshed = await asyncio.to_thread(_read_if_present, cookies_path)
            if refreshed is not None:
                await ctx.on_cookies_used(refreshed)
        return path
    finally:
        # Success, failure or cancel: the plaintext never outlives the step (§8).
        if cookies_path is not None:
            await asyncio.to_thread(cookies_path.unlink, True)


def _read_if_present(path: Path) -> str | None:
    try:
        return path.read_text()
    except FileNotFoundError:
        return None


async def _transcode(ctx: PipelineContext, video_path: Path) -> None:
    """Re-encode in place, holding the transcode slot only for this step (§6.1)."""
    started = perf_counter()
    # The file on disk is the truth: it is what the rename replaces and what mp4 flags apply to.
    container = video_path.suffix.lstrip(".") or ctx.options.container
    duration = await _duration(video_path)

    async with ctx.transcode_slot:
        _raise_if_cancelled(ctx)
        await ctx.set_status(JobStatus.TRANSCODING, Step.TRANSCODE)
        fell_back = await transcode(
            profile=ctx.options.transcode,
            source=video_path,
            job_dir=ctx.job_dir,
            container=container,
            quality=ctx.transcode_quality,
            duration=duration,
            cancel=ctx.cancel,
            on_percent=lambda pct: ctx.on_progress(Progress(status="transcoding", pct=pct)),
            on_log=ctx.on_log,
            driver=ctx.libva_driver,
        )

    await ctx.checkpoint(
        Step.TRANSCODE, perf_counter() - started, {"transcode_fallback_used": fell_back}
    )


async def _duration(video_path: Path) -> float | None:
    """The running time the percent is measured against; without it there is just no bar."""
    try:
        return (await probe(video_path)).duration
    except ProbeError:
        return None


async def _organize(ctx: PipelineContext, video_path: Path) -> None:
    started = perf_counter()
    await ctx.set_status(JobStatus.ORGANIZING, Step.ORGANIZE)
    result = await organize(
        ctx.job_dir,
        video_path,
        [],
        ctx.target,
        ctx.collision_policy,
        completed_dir=ctx.completed_dir,
        incomplete_dir=ctx.incomplete_dir,
    )
    ctx.completed_path = result.video
    await ctx.checkpoint(
        Step.ORGANIZE,
        perf_counter() - started,
        {
            "completed_path": str(result.video),
            "sidecar_paths": [str(path) for path in result.sidecars],
            "file_size": result.size,
        },
    )
    # Only once the checkpoint is committed (M3's note): the job dir is now disposable.
    await asyncio.to_thread(shutil.rmtree, ctx.job_dir, True)


# --------------------------------------------------------------------------- import (§7.5)


@dataclass(frozen=True)
class _ImportPlan:
    """Everything the import step needs, chosen once from the job's media type (§7.5)."""

    app: str
    client: RadarrClient | SonarrClient
    connection: ArrConnection
    #: `DownloadedMoviesScan` or `DownloadedEpisodesScan`.
    scan: str
    #: What the command carries: the movie's folder, or the episode's own file.
    send: Path
    #: Where the file sits: asked for rejections, and pruned once it is empty.
    folder: Path
    #: `completed/movies` or `completed/tv-shows`; pruning stops below it.
    root: Path
    #: The arr resource that says where the file went, or None for a manually typed title.
    lookup: Callable[[], Awaitable[dict[str, Any]]] | None
    #: The key that holds the library path in that resource.
    file_key: str


def _plan(ctx: PipelineContext, folder: Path) -> _ImportPlan | None:
    """The plan for this job, or None when its arr app isn't configured (§7.5)."""
    assert ctx.completed_path is not None  # noqa: S101 - organize always records it
    match ctx.target:
        case Movie():
            if ctx.radarr is None or ctx.radarr_connection is None:
                return None
            radarr, to_radarr = ctx.radarr, ctx.radarr_connection
            movie_id = ctx.radarr_movie_id
            return _ImportPlan(
                app=RADARR,
                client=radarr,
                connection=to_radarr,
                scan=MOVIE_SCAN,
                send=folder,
                folder=folder,
                root=ctx.completed_dir / "movies",
                lookup=(lambda: radarr.movie(to_radarr, movie_id))
                if movie_id is not None
                else None,
                file_key="movieFile",
            )
        case Episode() | DailyEpisode():
            if ctx.sonarr is None or ctx.sonarr_connection is None:
                return None
            sonarr, to_sonarr = ctx.sonarr, ctx.sonarr_connection
            episode_id = ctx.sonarr_episode_id
            return _ImportPlan(
                app=SONARR,
                client=sonarr,
                connection=to_sonarr,
                scan=EPISODE_SCAN,
                # Scoped as narrowly as §7.5 asks: the episode file itself.
                send=ctx.completed_path,
                folder=folder,
                root=ctx.completed_dir / "tv-shows",
                lookup=(lambda: sonarr.episode(to_sonarr, episode_id))
                if episode_id is not None
                else None,
                file_key="episodeFile",
            )
        case _:  # pragma: no cover - `other` never reaches the import step
            return None


async def _import(ctx: PipelineContext) -> None:
    """Ask arr to move the file into its library, then check that it really did."""
    started = perf_counter()
    await ctx.set_status(JobStatus.IMPORTING, Step.IMPORT)
    if ctx.completed_path is None:  # pragma: no cover - organize always records it
        raise RuntimeError("the import step needs a completed path")
    folder = ctx.completed_path.parent
    attempts = 0

    plan = _plan(ctx, folder)
    if plan is None:
        message = not_configured(SONARR if _is_episode(ctx.target) else RADARR)
        ctx.on_log(message)
        outcome = ImportOutcome(ImportStatus.NOT_IMPORTED, detail={"rejections": [message]})
    else:
        attempts, outcome = await _import_with_retries(ctx, plan)

    await ctx.checkpoint(
        Step.IMPORT,
        perf_counter() - started,
        {
            "import_status": outcome.status,
            "import_command_id": outcome.command_id,
            "import_attempts": attempts,
            "import_detail": outcome.detail,
            "imported_path": outcome.path,
            "imported_at": utcnow() if outcome.status is ImportStatus.IMPORTED else None,
        },
    )


def _is_episode(target: Target) -> bool:
    return isinstance(target, Episode | DailyEpisode)


async def _import_with_retries(
    ctx: PipelineContext, plan: _ImportPlan
) -> tuple[int, ImportOutcome]:
    """§6.1: four attempts over transport errors, 5xx and a polling timeout; nothing else."""
    attempts = 0
    last_command: list[str | None] = [None]

    async def before_sleep(state: RetryCallState) -> None:
        error = state.outcome.exception() if state.outcome else None
        wait = state.next_action.sleep if state.next_action else 0
        ctx.on_log(f"import attempt {state.attempt_number} failed ({error}); retrying in {wait:g}s")

    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(ctx.import_policy.attempts),
            wait=ctx.import_policy.wait,
            retry=retry_if_exception_type(IMPORT_RETRYABLE),
            before_sleep=before_sleep,
            reraise=True,
        ):
            with attempt:
                attempts = attempt.retry_state.attempt_number
                ctx.on_log(f"import attempt {attempts}: asking {plan.app} to import {plan.send}")
                return attempts, await _import_once(ctx, plan, last_command)
    except ArrAuthError as error:
        ctx.on_log(f"import failed: {error}")
        return attempts, _failed(f"{error}", last_command[0])
    except (ArrError, httpx.HTTPError) as error:
        ctx.on_log(f"import failed after {attempts} attempts: {error}")
        return attempts, _failed(str(error), last_command[0])
    raise AssertionError("unreachable")  # pragma: no cover - reraise=True always raises


async def _import_once(
    ctx: PipelineContext, plan: _ImportPlan, last_command: list[str | None]
) -> ImportOutcome:
    # Verification first: after a crash the command may already have done its work (§6.1).
    imported = await _verify(ctx, plan)
    if imported is not None:
        ctx.on_log(f"{plan.app} already has this file; nothing to send")
        return ImportOutcome(ImportStatus.IMPORTED, last_command[0], path=imported)

    # One import command at a time per arr app (§6.1).
    async with plan.client.import_lock:
        command_id = await _send_command(ctx, plan)
        last_command[0] = command_id
        ctx.on_log(f"{plan.app} command {command_id}: {plan.send}")
        await _poll(ctx, plan, command_id)
        imported = await _verify(ctx, plan)

    if imported is not None:
        return ImportOutcome(ImportStatus.IMPORTED, command_id, path=imported)
    # The file is still there, so arr refused it. Its reasons are a verdict, not an error.
    rejections = await plan.client.rejections(plan.connection, str(plan.folder))
    reasons = [rejection.reason for rejection in rejections]
    explanation = await _explain(ctx, plan, rejections)
    said = "; ".join(reasons) or "no reason given"
    ctx.on_log(
        f"{plan.app} did not import the file: {said}" + (f" — {explanation}" if explanation else "")
    )
    detail: dict[str, Any] = {"rejections": reasons}
    if explanation:
        detail["explanation"] = explanation
    return ImportOutcome(ImportStatus.NOT_IMPORTED, command_id, detail=detail)


async def _explain(
    ctx: PipelineContext, plan: _ImportPlan, rejections: list[Rejection]
) -> str | None:
    """Put a one-word verdict in context, from what fetcharr can measure itself (§7.5)."""
    sample = next((r for r in rejections if r.reason == SAMPLE), None)
    if sample is None:
        return None
    seconds: float | None = None
    if ctx.completed_path is not None:
        try:
            seconds = (await probe(ctx.completed_path)).duration
        except ProbeError:
            seconds = None
    return explain_rejection(sample, plan.app, seconds)


async def _send_command(ctx: PipelineContext, plan: _ImportPlan) -> str:
    """Send the narrow path, and fall back to the folder if arr won't take it (§7.5 step 1)."""
    try:
        return await plan.client.send_command(plan.connection, plan.scan, str(plan.send))
    except ArrClientError as error:
        if plan.send == plan.folder:
            raise
        ctx.on_log(f"{plan.app} refused the file path ({error}); sending {plan.folder} instead")
        return await plan.client.send_command(plan.connection, plan.scan, str(plan.folder))


async def _poll(ctx: PipelineContext, plan: _ImportPlan, command_id: str) -> None:
    """Poll until the command finishes, or give up with ArrTimeout (§7.5 step 2)."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + ctx.import_policy.command_timeout
    while True:
        status = (await plan.client.command(plan.connection, command_id)).lower()
        if status in FINISHED:
            return
        if loop.time() >= deadline:
            raise ArrTimeout(f"{plan.app} command {command_id} was still {status or 'unknown'}")
        await asyncio.sleep(ctx.import_policy.poll_interval)


async def _verify(ctx: PipelineContext, plan: _ImportPlan) -> str | None:
    """Imported = the file is gone from completed/ **and** arr has it (§7.5 step 3)."""
    assert ctx.completed_path is not None  # noqa: S101 - guarded by the caller
    if await asyncio.to_thread(ctx.completed_path.exists):
        return None

    library_path = ""
    if plan.lookup is not None:
        resource = await plan.lookup()
        library_path = str((resource.get(plan.file_key) or {}).get("path") or "")
        if not library_path:
            return None
    # The folders are ours and now empty, so they go; the category folder stays (§7.5).
    await asyncio.to_thread(prune_empty_dirs, plan.folder, plan.root)
    return library_path or None


def _failed(message: str, command_id: str | None) -> ImportOutcome:
    detail = {"error": message}
    if "API key" in message:
        detail["hint"] = BAD_KEY_HINT
    return ImportOutcome(ImportStatus.ERROR, command_id, detail=detail)
