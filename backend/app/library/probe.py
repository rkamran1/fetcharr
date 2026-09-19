"""Async ffprobe wrapper (requirements §7.4 step 2)."""

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path


class ProbeError(Exception):
    """ffprobe couldn't read the file."""


@dataclass(frozen=True)
class ProbeResult:
    width: int
    height: int
    vcodec: str | None
    acodec: str | None
    duration: float
    has_video: bool


async def probe(path: Path) -> ProbeResult:
    process = await asyncio.create_subprocess_exec(
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        raise ProbeError(
            f"ffprobe failed on {path.name}: {stderr.decode(errors='replace').strip()}"
        )
    try:
        info = json.loads(stdout)
        streams = info.get("streams", [])
        video = next((s for s in streams if s.get("codec_type") == "video"), None)
        audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
        return ProbeResult(
            width=int(video["width"]) if video else 0,
            height=int(video["height"]) if video else 0,
            vcodec=video.get("codec_name") if video else None,
            acodec=audio.get("codec_name") if audio else None,
            duration=float(info.get("format", {}).get("duration", 0)),
            has_video=video is not None,
        )
    except (ValueError, KeyError, TypeError) as error:
        raise ProbeError(f"unexpected ffprobe output for {path.name}") from error
