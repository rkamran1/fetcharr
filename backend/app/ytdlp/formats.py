"""Port of `get_format_selector` from download_video.sh."""

from app.ytdlp.schemas import Container, Quality

#: What the Intel iGPU can decode in hardware, best first (requirements §4.1).
GPU_DECODABLE = ("avc1", "vp9")

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


def build_selector(
    quality: Quality, container: Container, *, prefer_gpu_decode: bool = False
) -> str:
    height = _HEIGHTS[quality]
    hf = "" if height is None else f"[height<={height}]"
    plain = _script_selector(hf, container)
    if not prefer_gpu_decode:
        return plain
    # The UHD 630 decodes H.264 and VP9 on the GPU but not AV1, so a transcode asks for
    # those first and only then falls back to the script's own selector (§4.1).
    audio = "[ext=m4a]" if container == "mp4" else ""
    preferred = [f"bv*{hf}[vcodec^={codec}]+ba{audio}" for codec in GPU_DECODABLE]
    return "/".join([*preferred, plain])


def _script_selector(hf: str, container: Container) -> str:
    """`get_format_selector` from download_video.sh, unchanged (the M2 golden strings)."""
    if container == "mp4":
        # Prefer H.264 + M4A so the merge into MP4 is a pure copy on every player.
        return f"bv*{hf}[vcodec^=avc1]+ba[ext=m4a]/bv*{hf}[ext=mp4]+ba[ext=m4a]/bv*{hf}+ba/b{hf}"
    return f"bv*{hf}+ba/b{hf}"
