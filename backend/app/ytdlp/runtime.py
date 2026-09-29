"""Port of `detect_js_runtime` from download_video.sh, plus the runtime tools' versions."""

import asyncio
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

JsRuntime = Literal["deno", "node"]

#: yt-dlp lives in its own venv so it can be upgraded without touching the app's deps (§13.1).
YTDLP_VENV = Path("/opt/yt-dlp")
YTDLP_PIP = YTDLP_VENV / "bin" / "pip"
YTDLP_BIN = YTDLP_VENV / "bin" / "yt-dlp"
#: Long enough for a slow index, short enough that the request doesn't hang forever.
UPDATE_TIMEOUT_S = 180.0
#: A `--version` read is instant unless the binary is broken.
VERSION_TIMEOUT_S = 15.0
#: How much of pip's chatter comes back with the result.
OUTPUT_LINES = 40


class UpdateError(RuntimeError):
    """pip could not upgrade yt-dlp."""


@dataclass(frozen=True)
class ToolVersions:
    ytdlp: str | None
    ffmpeg: str | None
    deno: str | None


@dataclass(frozen=True)
class YtdlpUpdate:
    old: str | None
    new: str | None
    output: str


def detect_js_runtime() -> JsRuntime | None:
    """Find a JS runtime for YouTube's n-sig challenge: deno first, then node."""
    if shutil.which("deno") is None:
        # deno may be installed but missing from a non-interactive PATH.
        deno_bin = Path.home() / ".deno" / "bin"
        if os.access(deno_bin / "deno", os.X_OK):
            os.environ["PATH"] = f"{deno_bin}{os.pathsep}{os.environ.get('PATH', '')}"

    if shutil.which("deno") is not None:
        return "deno"
    if shutil.which("node") is not None:
        return "node"
    return None


def ytdlp_binary() -> str:
    """The venv's yt-dlp when it is there, otherwise whatever is on PATH (dev, tests)."""
    if os.access(YTDLP_BIN, os.X_OK):
        return str(YTDLP_BIN)
    return shutil.which("yt-dlp") or str(YTDLP_BIN)


async def _run(argv: list[str], seconds: float) -> tuple[int, str]:
    """Run a tool and collect its output; a missing binary is a failure, not a crash."""
    try:
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,
        )
    except OSError as error:
        return 127, str(error)
    try:
        async with asyncio.timeout(seconds):
            output, _ = await process.communicate()
    except TimeoutError:
        process.kill()
        await process.wait()
        return 124, f"{argv[0]} timed out after {seconds:.0f}s"
    return process.returncode or 0, output.decode(errors="replace").strip()


def _version(argv: list[str], field: int) -> str | None:
    """The `field`-th word of a tool's first version line, or None when it isn't there.

    Blocking: spawning three processes on the event loop stalls it for long enough to
    matter (§3.2), so every caller goes through a thread.
    """
    try:
        # A fixed argv, never a shell (§4).
        result = subprocess.run(
            argv, capture_output=True, text=True, timeout=VERSION_TIMEOUT_S, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    output = (result.stdout or result.stderr).strip()
    if result.returncode != 0 or not output:
        return None
    words = output.splitlines()[0].split()
    return words[field] if len(words) > field else None


def _tool_versions() -> ToolVersions:
    return ToolVersions(
        ytdlp=_version([ytdlp_binary(), "--version"], 0),
        ffmpeg=_version(["ffmpeg", "-version"], 2),
        deno=_version(["deno", "--version"], 1),
    )


async def tool_versions() -> ToolVersions:
    """yt-dlp, ffmpeg and deno as the Status page reports them (§11), read off the loop."""
    return await asyncio.to_thread(_tool_versions)


async def update_ytdlp() -> YtdlpUpdate:
    """`pip install --upgrade yt-dlp` inside the yt-dlp venv, and the versions around it."""
    old = await asyncio.to_thread(_version, [ytdlp_binary(), "--version"], 0)
    code, output = await _run(
        [str(YTDLP_PIP), "install", "--upgrade", "yt-dlp"], seconds=UPDATE_TIMEOUT_S
    )
    tail = "\n".join(output.splitlines()[-OUTPUT_LINES:])
    if code != 0:
        raise UpdateError(tail or f"pip exited {code}")
    new = await asyncio.to_thread(_version, [ytdlp_binary(), "--version"], 0)
    return YtdlpUpdate(old=old, new=new, output=tail)
