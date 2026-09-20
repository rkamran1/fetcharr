"""Run one yt-dlp download: live progress, process-group cancel and the §6.1 retry policy."""

import asyncio
import json
import os
import re
import signal
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from tenacity import (
    AsyncRetrying,
    RetryCallState,
    retry_if_exception_type,
    stop_after_attempt,
    wait_incrementing,
)

from app.ytdlp.command import downgrade_fragments
from app.ytdlp.inspect import classify_error

PROGRESS_PREFIX = "FA_PROGRESS "
FINAL_PATH_FILE = "final_path"
#: Time between SIGTERM and SIGKILL when a job is cancelled (requirements §6.1).
TERM_GRACE_S = 10.0
#: The script's schedule: sleep 4 s, 6 s, 8 s, … before attempts 2, 3, 4 …
DOWNLOAD_WAIT = wait_incrementing(start=4, increment=2)
#: Errors that won't fix themselves, so they are never retried (§6.1).
FATAL_KINDS = frozenset({"needs_cookies", "unsupported", "unavailable"})

# yt-dlp's post-processing lines, which mark the switch from downloading to merging/remuxing.
_POSTPROCESSING = re.compile(r"^\[(Merger|VideoRemuxer|VideoConvertor|ExtractAudio|ffmpeg)\]")
_PARTIAL_GLOBS = ("*.part", "*.ytdl", "*-Frag*.part", "*.temp.*")
#: Enough of the tail to classify the failure; the full log goes to job_logs as it arrives.
_ERROR_CONTEXT_LINES = 200


class YtDlpFailed(Exception):
    """A yt-dlp run that may well succeed on another attempt."""

    def __init__(self, exit_code: int, message: str) -> None:
        super().__init__(message)
        self.exit_code = exit_code
        self.message = message


class YtDlpFatal(Exception):
    """Unsupported, private or removed video, or cookies needed: retrying won't help."""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message


class DownloadCancelled(Exception):
    """The job was cancelled while yt-dlp was running."""


@dataclass(frozen=True)
class Progress:
    status: str
    downloaded_bytes: int = 0
    total_bytes: int | None = None
    speed_bps: float | None = None
    eta_s: int | None = None
    pct: float | None = None
    #: True once yt-dlp is merging or remuxing, which is the `postprocessing` phase.
    postprocessing: bool = False


OnProgress = Callable[[Progress], None]
OnLog = Callable[[str], None]


def parse_progress(line: str) -> Progress | None:
    """One `FA_PROGRESS {...}` line from `--progress-template`, or None for anything else."""
    if not line.startswith(PROGRESS_PREFIX):
        return None
    try:
        data: Any = json.loads(line[len(PROGRESS_PREFIX) :])
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None

    downloaded = int(data.get("downloaded_bytes") or 0)
    # Fragmented downloads only know an estimate.
    total_raw = data.get("total_bytes") or data.get("total_bytes_estimate")
    total = int(total_raw) if total_raw else None
    return Progress(
        status=str(data.get("status") or "downloading"),
        downloaded_bytes=downloaded,
        total_bytes=total,
        speed_bps=float(data["speed"]) if data.get("speed") else None,
        eta_s=int(data["eta"]) if data.get("eta") else None,
        pct=round(100 * downloaded / total, 1) if total else None,
    )


def is_postprocessing(line: str) -> bool:
    """True for the yt-dlp lines that mean merging or remuxing has started."""
    return _POSTPROCESSING.match(line) is not None


def read_final_path(job_dir: Path) -> Path:
    """The path yt-dlp printed with `after_move:%(filepath)s` (the last line it appended)."""
    marker = job_dir / FINAL_PATH_FILE
    lines = [line.strip() for line in marker.read_text().splitlines() if line.strip()]
    if not lines:
        raise YtDlpFailed(0, "yt-dlp reported no output file")
    return Path(lines[-1])


def cleanup_partials(job_dir: Path) -> None:
    """Remove yt-dlp's leftovers, inside this job dir only (never a sibling's)."""
    for pattern in _PARTIAL_GLOBS:
        for path in job_dir.rglob(pattern):
            if path.is_file():
                path.unlink(missing_ok=True)


def _terminate(pid: int, sig: int) -> None:
    try:
        os.killpg(pid, sig)
    except (ProcessLookupError, PermissionError):
        pass


async def _kill_when_cancelled(cancel: asyncio.Event, pid: int, alive: Callable[[], bool]) -> None:
    """SIGTERM the process group, then SIGKILL it if it's still there (§6.1)."""
    await cancel.wait()
    _terminate(pid, signal.SIGTERM)
    await asyncio.sleep(TERM_GRACE_S)
    if alive():
        _terminate(pid, signal.SIGKILL)


async def run_once(
    argv: list[str],
    *,
    job_dir: Path,
    cancel: asyncio.Event,
    on_progress: OnProgress,
    on_log: OnLog,
    binary: str = "yt-dlp",
) -> Path:
    """One yt-dlp attempt: stream its output, then return the downloaded file's path."""
    process = await asyncio.create_subprocess_exec(
        binary,
        *argv,
        stdout=asyncio.subprocess.PIPE,
        # Merged on purpose: progress and errors keep their order in the log.
        stderr=asyncio.subprocess.STDOUT,
        start_new_session=True,
    )
    stdout = process.stdout
    if stdout is None:  # pragma: no cover - PIPE always gives a stream
        raise YtDlpFailed(0, "yt-dlp produced no output stream")
    killer = asyncio.create_task(
        _kill_when_cancelled(cancel, process.pid, lambda: process.returncode is None)
    )

    tail: list[str] = []
    postprocessing = False
    try:
        async for raw in stdout:
            line = raw.decode(errors="replace").rstrip()
            if not line:
                continue
            progress = parse_progress(line)
            if progress is not None:
                on_progress(replace(progress, postprocessing=postprocessing))
                continue
            if not postprocessing and is_postprocessing(line):
                postprocessing = True
                on_progress(Progress(status="postprocessing", postprocessing=True))
            tail.append(line)
            del tail[:-_ERROR_CONTEXT_LINES]
            on_log(line)
        returncode = await process.wait()
    finally:
        killer.cancel()
        await asyncio.gather(killer, return_exceptions=True)
        if process.returncode is None:
            _terminate(process.pid, signal.SIGKILL)
            await process.wait()

    if cancel.is_set():
        raise DownloadCancelled("cancelled")
    if returncode != 0:
        error = classify_error("\n".join(tail))
        if error.kind in FATAL_KINDS:
            raise YtDlpFatal(error.kind, error.message)
        raise YtDlpFailed(returncode, error.message)
    return read_final_path(job_dir)


async def download(
    argv: list[str],
    *,
    job_dir: Path,
    retries: int,
    cancel: asyncio.Event,
    on_progress: OnProgress,
    on_log: OnLog,
    on_attempt: Callable[[int], None] = lambda _attempt: None,
    wait: Any = DOWNLOAD_WAIT,
    binary: str = "yt-dlp",
) -> Path:
    """Run yt-dlp with the script's retry schedule; `YtDlpFatal` is never retried (§6.1)."""
    current_argv = list(argv)
    attempts = 0

    async def attempt() -> Path:
        nonlocal attempts
        attempts += 1
        on_attempt(attempts)
        on_log(f"yt-dlp attempt {attempts}")
        return await run_once(
            current_argv,
            job_dir=job_dir,
            cancel=cancel,
            on_progress=on_progress,
            on_log=on_log,
            binary=binary,
        )

    async def before_sleep(retry_state: RetryCallState) -> None:
        nonlocal current_argv
        outcome = retry_state.outcome
        error = outcome.exception() if outcome is not None else None
        sleep = retry_state.next_action.sleep if retry_state.next_action is not None else 0
        on_log(f"attempt {retry_state.attempt_number} failed ({error}); retrying in {sleep:g}s")
        # The script's exit-code-2 fallback: one fragment at a time from now on.
        if isinstance(error, YtDlpFailed) and error.exit_code == 2:
            current_argv = downgrade_fragments(current_argv)
            on_log("exit code 2: continuing with --concurrent-fragments 1")

    retrying = AsyncRetrying(
        stop=stop_after_attempt(retries + 1),
        wait=wait,
        retry=retry_if_exception_type(YtDlpFailed),
        before_sleep=before_sleep,
        reraise=True,
    )
    return await retrying(attempt)
