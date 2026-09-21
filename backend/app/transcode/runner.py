"""Run one ffmpeg transcode: live percent, process-group cancel and the §6.1 fallback.

The step is safe to re-run: it writes to `transcoded.tmp.<ext>`, replaces the source with a
single rename, and only then writes the `transcode.done` marker. A half-written temp file
from a crash is deleted and the transcode is redone (§6.1).
"""

import asyncio
import os
import re
import signal
from collections.abc import Callable, Mapping
from pathlib import Path

from app.transcode.profiles import (
    HARDWARE,
    TEMP_GLOB,
    TranscodeProfile,
    build_argv,
    marker,
    quality_for,
    temp_output,
)

#: Time between SIGTERM and SIGKILL when a job is cancelled (requirements §6.1).
TERM_GRACE_S = 10.0
#: Enough of the tail to explain the failure; the full output goes to job_logs as it arrives.
_ERROR_CONTEXT_LINES = 200
#: The one `-progress` key that carries a timestamp, and the key that ends a run.
_TIME_KEY = "out_time_us"
_PROGRESS_KEY = "progress"
_MICROSECONDS = 1_000_000
#: Every key `-progress` emits (ffmpeg 8). Anything else on the stream is log output, so an
#: error line that happens to contain an `=` still reaches the job log.
_PROGRESS_LINE = re.compile(
    r"^(?:frame|fps|bitrate|total_size|out_time_us|out_time_ms|out_time|dup_frames"
    r"|drop_frames|speed|progress|stream_\d+_\d+_q)=",
)

OnPercent = Callable[[float], None]
OnLog = Callable[[str], None]


class TranscodeFailed(Exception):
    """ffmpeg exited non-zero. A hardware profile falls back; x265 fails the step (§6.1)."""

    def __init__(self, exit_code: int, message: str) -> None:
        super().__init__(message)
        self.exit_code = exit_code
        self.message = message


class TranscodeCancelled(Exception):
    """The job was cancelled while ffmpeg was running."""


def percent(line: str, duration: float | None) -> float | None:
    """One `key=value` line from `-progress pipe:1`, as a percentage, or None (§4.1)."""
    key, separator, value = line.partition("=")
    if not separator:
        return None
    key, value = key.strip(), value.strip()
    if key == _PROGRESS_KEY:
        return 100.0 if value == "end" else None
    if key != _TIME_KEY or not duration or duration <= 0:
        return None
    try:
        elapsed = int(value)
    except ValueError:
        # ffmpeg reports `N/A` until the first frame is written.
        return None
    return min(100.0, round(100 * elapsed / (duration * _MICROSECONDS), 1))


def clear_temp_files(job_dir: Path) -> None:
    """Drop any `transcoded.tmp.*` a crash left behind (§6.1: the filesystem wins)."""
    for path in job_dir.glob(TEMP_GLOB):
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


def _environment(driver: str) -> dict[str, str]:
    """libva picks its driver from the environment, so the setting has to reach ffmpeg."""
    return {**os.environ, "LIBVA_DRIVER_NAME": driver}


async def run_once(
    argv: list[str],
    *,
    cancel: asyncio.Event,
    on_percent: OnPercent,
    on_log: OnLog,
    duration: float | None,
    driver: str,
    binary: str = "ffmpeg",
) -> None:
    """One ffmpeg run: stream `-progress` from stdout and everything else into the log."""
    process = await asyncio.create_subprocess_exec(
        binary,
        *argv,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        # Merged on purpose: progress and errors keep their order in one log.
        stderr=asyncio.subprocess.STDOUT,
        start_new_session=True,
        env=_environment(driver),
    )
    stdout = process.stdout
    if stdout is None:  # pragma: no cover - PIPE always gives a stream
        raise TranscodeFailed(0, "ffmpeg produced no output stream")
    killer = asyncio.create_task(
        _kill_when_cancelled(cancel, process.pid, lambda: process.returncode is None)
    )

    tail: list[str] = []
    try:
        async for raw in stdout:
            line = raw.decode(errors="replace").rstrip()
            if not line:
                continue
            reached = percent(line, duration)
            if reached is not None:
                on_percent(reached)
                continue
            if _PROGRESS_LINE.match(line):
                # Another `-progress` key (bitrate, fps, …); noise in a job log.
                continue
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
        raise TranscodeCancelled("cancelled")
    if returncode != 0:
        raise TranscodeFailed(returncode, _reason(tail))


def _reason(tail: list[str]) -> str:
    for line in reversed(tail):
        if line.strip():
            return line.strip()
    return "ffmpeg failed with no output"


async def transcode(
    *,
    profile: TranscodeProfile,
    source: Path,
    job_dir: Path,
    container: str,
    quality: Mapping[str, int] | None,
    duration: float | None,
    cancel: asyncio.Event,
    on_percent: OnPercent,
    on_log: OnLog,
    driver: str,
    binary: str = "ffmpeg",
) -> bool:
    """Re-encode `source` in place. True when the hardware profile fell back to x265 (§6.1)."""
    configured = dict(quality or {})
    output = temp_output(job_dir, container)
    await asyncio.to_thread(clear_temp_files, job_dir)

    async def encode(chosen: TranscodeProfile) -> None:
        argv = build_argv(
            chosen,
            source,
            output,
            container=container,
            quality=quality_for(chosen, configured),
        )
        on_log(f"transcoding with {chosen}: {' '.join(argv)}")
        await run_once(
            argv,
            cancel=cancel,
            on_percent=on_percent,
            on_log=on_log,
            duration=duration,
            driver=driver,
            binary=binary,
        )

    fell_back = False
    try:
        await encode(profile)
    except TranscodeFailed as error:
        # Not a retry but a fallback, and exactly once: plain code, not tenacity (§6.1).
        if profile not in HARDWARE:
            raise
        fallback = TranscodeProfile.X265_SOFTWARE
        on_log(f"{profile} failed ({error.message}); falling back to {fallback}")
        await asyncio.to_thread(output.unlink, True)
        await encode(fallback)
        fell_back = True

    await asyncio.to_thread(_replace_source, output, source, job_dir)
    on_log(f"transcoded {source.name}")
    return fell_back


def _replace_source(output: Path, source: Path, job_dir: Path) -> None:
    """The source is only ever replaced by one atomic rename, then the marker goes down."""
    os.replace(output, source)
    marker(job_dir).write_text("done\n")
