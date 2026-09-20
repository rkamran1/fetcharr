"""Small pure helpers for the jobs domain."""

from pathlib import Path

from app.ytdlp.stream import StreamType


def as_stream_type(value: str | None) -> StreamType:
    """A stored stream type, falling back to `http` (the script's default behaviour)."""
    match value:
        case "hls" | "dash" | "http":
            return value
        case _:
            return "http"


def is_inside(path: Path, *roots: Path) -> bool:
    """True when `path` resolves inside one of the roots (§7.4 path guard)."""
    resolved = path.resolve()
    return any(resolved.is_relative_to(root.resolve()) for root in roots)
