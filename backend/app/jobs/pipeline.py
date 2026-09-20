"""The four checkpointed steps of one job (requirements §6.1).

The pipeline owns no database code: every write goes through the callbacks in
``PipelineContext``, which the JobManager supplies. That is what keeps a write transaction
from ever spanning the yt-dlp subprocess (§3.1 rule 2).
"""

import asyncio
import shutil
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from typing import Any

from app.jobs.constants import STEPS, JobStatus, Step
from app.library.naming import Other
from app.library.organizer import CollisionPolicy, is_organized, organize
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


@dataclass
class PipelineContext:
    job_id: str
    url: str
    options: DownloadOptions
    stream_type: StreamType
    target: Other
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
    #: Injectable so tests run the retry policy without sleeping (§6.1).
    download_wait: Any = DOWNLOAD_WAIT
    step_timings: dict[str, float] = field(default_factory=dict)


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
            # `other` jobs have nothing to import; M5b/M6 add the real step.
            pass

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
        CollisionPolicy.KEEP_BOTH,
        completed_dir=ctx.completed_dir,
        incomplete_dir=ctx.incomplete_dir,
    )
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
