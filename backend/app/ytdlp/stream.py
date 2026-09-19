"""Port of `detect_stream_type` from download_video.sh."""

from dataclasses import dataclass
from typing import Any, Literal

from app.ytdlp.options import DownloadOptions

StreamType = Literal["hls", "dash", "http"]


@dataclass(frozen=True)
class Resolved:
    stream_type: StreamType
    fragments: int
    use_aria2c: bool


def classify(info_json: dict[str, Any]) -> StreamType:
    """Classify the formats yt-dlp selected (`-J` output), HLS first, then DASH, else HTTP."""
    selected = info_json.get("requested_formats") or [info_json]
    protocols = [p for f in selected for p in (f.get("protocol") or "").split("+")]
    if any(p.startswith("m3u8") for p in protocols):
        return "hls"
    # YouTube's adaptive formats are protocol "https" with container "mp4_dash"/"webm_dash";
    # the script's grep for "dash" in `-F` output caught those too.
    if any("dash" in p for p in protocols) or any(
        (f.get("container") or "").endswith("_dash") for f in selected
    ):
        return "dash"
    return "http"


def resolve_auto(
    stream_type: StreamType, options: DownloadOptions, aria2c_available: bool
) -> Resolved:
    if options.fragments == "auto":
        fragments = 1 if stream_type == "http" else 4
    else:
        fragments = options.fragments

    if options.use_aria2c == "auto":
        use_aria2c = stream_type == "http" and aria2c_available
    else:
        use_aria2c = options.use_aria2c and aria2c_available

    return Resolved(stream_type=stream_type, fragments=fragments, use_aria2c=use_aria2c)
