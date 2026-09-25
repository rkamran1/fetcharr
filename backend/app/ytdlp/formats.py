"""Port of `get_format_selector` from download_video.sh."""

from app.ytdlp.schemas import Container, Quality, VideoCodec

#: What the Intel iGPU can decode in hardware, best first (requirements §4.1).
GPU_DECODABLE = ("avc1", "vp9")
#: The `vcodec^=` prefix each codec preference asks for (§5 step 2d).
CODEC_PREFIXES: dict[VideoCodec, str] = {"h264": "avc1", "vp9": "vp9", "av1": "av01"}

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
    quality: Quality,
    container: Container,
    *,
    prefer_gpu_decode: bool = False,
    video_codec: VideoCodec = "any",
    audio_language: str | None = None,
    allow_hdr: bool = True,
) -> str:
    """The script's selector, with the user's preferences prepended as earlier alternatives.

    Every preference is a preference, never a filter: the script's own selector is always the
    last alternative, so a video that has nothing matching still downloads (§5 step 2d).
    """
    height = _HEIGHTS[quality]
    hf = "" if height is None else f"[height<={height}]"
    plain = _script_selector(hf, container)

    if video_codec != "any":
        codecs: tuple[str, ...] = (CODEC_PREFIXES[video_codec],)
    elif prefer_gpu_decode:
        # The UHD 630 decodes H.264 and VP9 on the GPU but not AV1, so a transcode asks for
        # those first and only then falls back to the script's own selector (§4.1).
        codecs = GPU_DECODABLE
    else:
        codecs = ()

    # `dynamic_range` is a string per format (`SDR`, `HDR10`, `HLG`), not a flag.
    sdr = "" if allow_hdr else "[dynamic_range=SDR]"
    audio = "[ext=m4a]" if container == "mp4" else ""
    language = "" if audio_language is None else f"[language={audio_language}]"

    video_terms = [f"[vcodec^={codec}]" for codec in codecs] or ([""] if sdr or language else [])
    preferred = [f"bv*{hf}{term}{sdr}+ba{audio}{language}" for term in video_terms]
    return "/".join([*preferred, plain])


def _script_selector(hf: str, container: Container) -> str:
    """`get_format_selector` from download_video.sh, unchanged (the M2 golden strings)."""
    if container == "mp4":
        # Prefer H.264 + M4A so the merge into MP4 is a pure copy on every player.
        return f"bv*{hf}[vcodec^=avc1]+ba[ext=m4a]/bv*{hf}[ext=mp4]+ba[ext=m4a]/bv*{hf}+ba/b{hf}"
    return f"bv*{hf}+ba/b{hf}"
