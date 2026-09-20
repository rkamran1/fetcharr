"""Pure helpers for the request shapes and the path preview (requirements §5, §7.2)."""

from typing import Any

from app.library.naming import quality_label
from app.ytdlp.schemas import DownloadOptions

#: `4k` isn't a height; every other quality is "<height>p".
QUALITY_HEIGHTS = {"4k": 2160}


def estimated_quality(info: dict[str, Any], options: DownloadOptions) -> str:
    """The `{Quality Full}` the download will most likely produce.

    The real label comes from ffprobe after the download (§7.2); the preview can only
    guess, from the heights the inspection found and the quality ceiling that was asked for.
    """
    heights = sorted(_heights(info))
    ceiling = _ceiling(options.quality)
    if ceiling is None:
        height = heights[-1] if heights else 0
    else:
        below = [value for value in heights if value <= ceiling]
        height = below[-1] if below else ceiling
    return quality_label(height, height) if height else ""


def _heights(info: dict[str, Any]) -> set[int]:
    found = set()
    for value in info.get("video_heights") or []:
        try:
            height = int(value)
        except (TypeError, ValueError):
            continue
        if height > 0:
            found.add(height)
    return found


def _ceiling(quality: str) -> int | None:
    if quality == "best":
        return None
    if quality in QUALITY_HEIGHTS:
        return QUALITY_HEIGHTS[quality]
    return int(quality.removesuffix("p"))
