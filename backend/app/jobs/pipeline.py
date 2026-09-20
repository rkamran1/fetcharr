"""The four checkpointed steps of one job (requirements §6.1).

The pipeline owns no database code: every write goes through the callbacks in
``PipelineContext``, which the JobManager supplies. That is what keeps a write transaction
from ever spanning the yt-dlp subprocess or a call to Radarr (§3.1 rule 2).
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
    ArrAuthError,
    ArrConnection,
    ArrError,
    ArrServerError,
    ArrTimeout,
    ImportPolicy,
    RadarrClient,
)
from app.jobs.constants import STEPS, ImportStatus, JobStatus, Step
from app.library.naming import Movie, Target
from app.library.organizer import CollisionPolicy, is_organized, organize, prune_empty_dirs
from app.library.probe import ProbeError, probe
from app.ytdlp.command import build_argv
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
NOT_CONFIGURED = "Radarr is not configured in Settings"
BAD_KEY_HINT = "check the API key in Settings"


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
    checkpoint: Checkpoint
    set_status: SetStatus
    on_progress: Callable[[Progress], None]
    on_log: Callable[[str], None]
    on_attempt: Callable[[int], None]
    aria2c_available: bool = False
    js_runtime: JsRuntime | None = None
    last_completed_step: Step | None = None
    completed_path: Path | None = None
    collision_policy: CollisionPolicy = CollisionPolicy.KEEP_BOTH
    #: The import half (§7.5); only a movie target ever uses it.
    import_status: str = ImportStatus.NOT_APPLICABLE
    radarr_movie_id: int | None = None
    radarr: RadarrClient | None = None
    radarr_connection: ArrConnection | None = None
    import_policy: ImportPolicy = field(default_factory=ImportPolicy)
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
            # Nothing is ever requested in M5a, so the done-check always skips it (M7).
            pass

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
            if isinstance(ctx.target, Movie) and ctx.import_status not in IMPORT_DONE:
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
    argv = build_argv(
        ctx.url,
        ctx.options,
        resolved,
        job_dir=ctx.job_dir,
        js_runtime=ctx.js_runtime,
    )
    # The download slot is held only for this step (§6.1).
    async with ctx.download_slot:
        _raise_if_cancelled(ctx)
        await ctx.set_status(JobStatus.DOWNLOADING, Step.DOWNLOAD)
        try:
            return await download(
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


async def _import(ctx: PipelineContext) -> None:
    """Ask Radarr to move the file into its library, then check that it really did."""
    started = perf_counter()
    await ctx.set_status(JobStatus.IMPORTING, Step.IMPORT)
    if ctx.completed_path is None:  # pragma: no cover - organize always records it
        raise RuntimeError("the import step needs a completed path")
    folder = ctx.completed_path.parent
    attempts = 0

    if ctx.radarr is None or ctx.radarr_connection is None:
        ctx.on_log(NOT_CONFIGURED)
        outcome = ImportOutcome(ImportStatus.NOT_IMPORTED, detail={"rejections": [NOT_CONFIGURED]})
    else:
        attempts, outcome = await _import_with_retries(ctx, folder)

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


async def _import_with_retries(ctx: PipelineContext, folder: Path) -> tuple[int, ImportOutcome]:
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
                ctx.on_log(f"import attempt {attempts}: asking Radarr to import {folder}")
                return attempts, await _import_once(ctx, folder, last_command)
    except ArrAuthError as error:
        ctx.on_log(f"import failed: {error}")
        return attempts, _failed(f"{error}", last_command[0])
    except (ArrError, httpx.HTTPError) as error:
        ctx.on_log(f"import failed after {attempts} attempts: {error}")
        return attempts, _failed(str(error), last_command[0])
    raise AssertionError("unreachable")  # pragma: no cover - reraise=True always raises


async def _import_once(
    ctx: PipelineContext, folder: Path, last_command: list[str | None]
) -> ImportOutcome:
    client, connection = ctx.radarr, ctx.radarr_connection
    assert client is not None and connection is not None  # noqa: S101 - guarded by the caller

    # Verification first: after a crash the command may already have done its work (§6.1).
    imported = await _verify(ctx, folder)
    if imported is not None:
        ctx.on_log("Radarr already has this file; nothing to send")
        return ImportOutcome(ImportStatus.IMPORTED, last_command[0], path=imported)

    # One import command at a time per arr app (§6.1).
    async with client.import_lock:
        command_id = await client.send_command(connection, str(folder))
        last_command[0] = command_id
        ctx.on_log(f"Radarr command {command_id}: {folder}")
        await _poll(ctx, command_id)
        imported = await _verify(ctx, folder)

    if imported is not None:
        return ImportOutcome(ImportStatus.IMPORTED, command_id, path=imported)
    # The file is still there, so Radarr refused it. Its reasons are a verdict, not an error.
    reasons = await client.rejections(connection, str(folder))
    ctx.on_log(f"Radarr did not import the file: {'; '.join(reasons) or 'no reason given'}")
    return ImportOutcome(ImportStatus.NOT_IMPORTED, command_id, detail={"rejections": reasons})


async def _poll(ctx: PipelineContext, command_id: str) -> None:
    """Poll until the command finishes, or give up with ArrTimeout (§7.5 step 2)."""
    client, connection = ctx.radarr, ctx.radarr_connection
    assert client is not None and connection is not None  # noqa: S101 - guarded by the caller
    loop = asyncio.get_running_loop()
    deadline = loop.time() + ctx.import_policy.command_timeout
    while True:
        status = (await client.command(connection, command_id)).lower()
        if status in ("completed", "failed", "aborted"):
            return
        if loop.time() >= deadline:
            raise ArrTimeout(f"Radarr command {command_id} was still {status or 'unknown'}")
        await asyncio.sleep(ctx.import_policy.poll_interval)


async def _verify(ctx: PipelineContext, folder: Path) -> str | None:
    """Imported = the file is gone from completed/ **and** Radarr has it (§7.5 step 3)."""
    client, connection = ctx.radarr, ctx.radarr_connection
    assert client is not None and connection is not None  # noqa: S101 - guarded by the caller
    assert ctx.completed_path is not None  # noqa: S101 - guarded by the caller
    if await asyncio.to_thread(ctx.completed_path.exists):
        return None

    library_path = ""
    if ctx.radarr_movie_id is not None:
        movie = await client.movie(connection, ctx.radarr_movie_id)
        library_path = str((movie.get("movieFile") or {}).get("path") or "")
        if not library_path:
            return None
    # The folder is ours and now empty, so it goes; `movies/` itself always stays (§7.5).
    await asyncio.to_thread(prune_empty_dirs, folder, ctx.completed_dir / "movies")
    return library_path or None


def _failed(message: str, command_id: str | None) -> ImportOutcome:
    detail = {"error": message}
    if "API key" in message:
        detail["hint"] = BAD_KEY_HINT
    return ImportOutcome(ImportStatus.ERROR, command_id, detail=detail)
