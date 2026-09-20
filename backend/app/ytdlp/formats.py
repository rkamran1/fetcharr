"""Port of `get_format_selector` from download_video.sh."""

from app.ytdlp.schemas import Container, Quality

_HEIGHTS: dict[Quality, int | None] = {
    "144p": 144,
    "240p": 240,
    "360p": 360,
    "480p": 480,
    "720p": 720,
    "1080p": 1080,
    "1440p": 1440,
    "2160p": 2160,
    "4k": 2160,
    "best": None,
}


def build_selector(quality: Quality, container: Container) -> str:
    height = _HEIGHTS[quality]
    hf = "" if height is None else f"[height<={height}]"
    if container == "mp4":
        # Prefer H.264 + M4A so the merge into MP4 is a pure copy on every player.
        return f"bv*{hf}[vcodec^=avc1]+ba[ext=m4a]/bv*{hf}[ext=mp4]+ba[ext=m4a]/bv*{hf}+ba/b{hf}"
    return f"bv*{hf}+ba/b{hf}"
