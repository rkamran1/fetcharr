"""The yt-dlp side of step 1 (requirements §5): `yt-dlp -J` argv, run, stderr classification."""

import asyncio
import json
import os
import re
import signal
from typing import Any, Literal

from app.ytdlp.command import is_youtube_url
from app.ytdlp.runtime import JsRuntime

INSPECT_TIMEOUT_S = 60.0

_NEEDS_COOKIES = re.compile(
    r"sign in|log ?in required|\bage\b|members[- ]only|private", re.IGNORECASE
)
_UNAVAILABLE = re.compile(
    r"unavailable|removed|deleted|not available|not found|does not exist|no longer",
    re.IGNORECASE,
)
_EXTRACTOR_PREFIX = re.compile(r"^\[[^\]]+\] [^:]+: ")

ErrorKind = Literal["needs_cookies", "unsupported", "unavailable", "timeout", "failed"]


class YtdlpError(Exception):
    def __init__(self, kind: ErrorKind, message: str) -> None:
        super().__init__(message)
        self.kind: ErrorKind = kind
        self.message = message


def build_inspect_argv(url: str, js_runtime: JsRuntime | None) -> list[str]:
    """The yt-dlp arguments (without the binary) for inspecting one URL."""
    argv = ["-J", "--no-download", "--no-playlist"]
    # Same YouTube n-sig solver rule as the download command (build_argv).
    if is_youtube_url(url):
        argv += ["--remote-components", "ejs:github"]
        if js_runtime == "node":
            argv += ["--js-runtimes", "node"]
    argv.append(url)
    return argv


def classify_error(stderr: str) -> YtdlpError:
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    errors = [line for line in lines if line.startswith("ERROR:")]
    last = errors[-1] if errors else (lines[-1] if lines else "yt-dlp failed")
    message = _EXTRACTOR_PREFIX.sub("", last.removeprefix("ERROR:").strip())

    if _NEEDS_COOKIES.search(message):
        return YtdlpError("needs_cookies", message)
    if "Unsupported URL" in message:
        return YtdlpError("unsupported", "Unsupported URL")
    if _UNAVAILABLE.search(message):
        return YtdlpError("unavailable", message)
    return YtdlpError("failed", last)


def _parse(stdout: bytes) -> Any:
    try:
        return json.loads(stdout)
    except ValueError as error:
        raise YtdlpError("failed", "yt-dlp returned unreadable output") from error


async def run_json(argv: list[str]) -> Any:
    """Run `yt-dlp <argv>` and return its parsed JSON output, or raise YtdlpError."""
    process = await asyncio.create_subprocess_exec(
        "yt-dlp",
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), INSPECT_TIMEOUT_S)
    except TimeoutError:
        # start_new_session made yt-dlp a process-group leader; kill its children too.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await process.wait()
        raise YtdlpError("timeout", f"yt-dlp timed out after {INSPECT_TIMEOUT_S:g} s") from None

    if process.returncode != 0:
        raise classify_error(stderr.decode(errors="replace"))
    # A YouTube -J is about 1 MB of JSON: parse it off the event loop.
    return await asyncio.to_thread(_parse, stdout)
