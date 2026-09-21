"""Sync filesystem and ffprobe helpers; ruff's ASYNC rules keep them out of async bodies."""

import json
import subprocess
from pathlib import Path


def copy_media(source: Path, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(source.read_bytes())
    return destination


def write(path: Path, text: str = "stale") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def read_bytes(path: Path) -> bytes:
    return path.read_bytes()


def listing(directory: Path) -> list[str]:
    return sorted(entry.name for entry in directory.iterdir()) if directory.is_dir() else []


def video_codec(path: Path) -> tuple[str, str]:
    """`(codec_name, codec_tag_string)` of the first video stream, straight from ffprobe."""
    output = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,codec_tag_string",
            "-print_format",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    stream = json.loads(output)["streams"][0]
    return stream["codec_name"], stream["codec_tag_string"]
