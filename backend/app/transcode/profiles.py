"""The ffmpeg transcode profiles and their argv (requirements §4.1).

`x265-software` is `download_video.sh`'s own transcode, kept word for word; the golden test
in `tests/golden/test_transcode_args.py` is what keeps it that way. The two hardware profiles
are the UHD 630 paths from §4.1, with the quality value calibrated on the real box (§0).
"""

from enum import StrEnum
from pathlib import Path


class TranscodeProfile(StrEnum):
    """What a download is re-encoded with; `off` means it is only remuxed (§5 step 2d)."""

    OFF = "off"
    HEVC_QSV = "hevc-qsv"
    HEVC_VAAPI = "hevc-vaapi"
    X265_SOFTWARE = "x265-software"


#: The profiles that need the iGPU. A failure in one of these falls back to x265 (§6.1).
HARDWARE = (TranscodeProfile.HEVC_QSV, TranscodeProfile.HEVC_VAAPI)
#: QSV/VAAPI `global_quality` is not x265's CRF, so it is calibrated once on the box (§4.1).
DEFAULT_QUALITY: dict[TranscodeProfile, int] = {
    TranscodeProfile.HEVC_QSV: 24,
    TranscodeProfile.HEVC_VAAPI: 24,
    TranscodeProfile.X265_SOFTWARE: 23,
}
QUALITY_MIN = 1
QUALITY_MAX = 51

#: The render node the iGPU appears as inside the container (§13.4).
RENDER_DEVICE = Path("/dev/dri/renderD128")

#: Shared by every profile, and the script's own audio settings (§4.1).
AUDIO_ARGS = ["-c:a", "aac", "-b:a", "128k"]
#: `-map 0` with subtitle and chapter copy (§4.1).
MAP_ARGS = ["-map", "0", "-c:s", "copy", "-map_chapters", "0"]
#: The script's mp4 extras: playable in QuickTime/Safari, streamable from the first byte.
MP4_ARGS = ["-tag:v", "hvc1", "-movflags", "+faststart"]
#: Machine-readable progress on stdout, no prompts, and no half-written leftovers (§4.1).
BASE_ARGS = [
    "-nostdin",
    "-hide_banner",
    "-loglevel",
    "error",
    "-progress",
    "pipe:1",
    "-nostats",
    "-y",
]

#: The transcode writes here and only replaces the source once it succeeded (§6.1).
TEMP_STEM = "transcoded.tmp"
TEMP_GLOB = f"{TEMP_STEM}.*"
#: The transcode step's done-check marker (§6.1).
DONE_MARKER = "transcode.done"


def input_args(profile: TranscodeProfile) -> list[str]:
    """The hardware setup flags, which ffmpeg only accepts before `-i` (§4.1)."""
    match profile:
        case TranscodeProfile.HEVC_QSV:
            return [
                "-init_hw_device",
                "qsv=hw",
                "-filter_hw_device",
                "hw",
                "-hwaccel",
                "qsv",
                "-hwaccel_output_format",
                "qsv",
            ]
        case TranscodeProfile.HEVC_VAAPI:
            return ["-vaapi_device", str(RENDER_DEVICE)]
        case _:
            return []


def video_args(profile: TranscodeProfile, quality: int) -> list[str]:
    """The encoder flags for one profile at one quality (§4.1)."""
    match profile:
        case TranscodeProfile.HEVC_QSV:
            return [
                "-c:v",
                "hevc_qsv",
                "-preset",
                "medium",
                "-global_quality",
                str(quality),
                "-look_ahead",
                "1",
            ]
        case TranscodeProfile.HEVC_VAAPI:
            return [
                "-vf",
                "format=nv12,hwupload",
                "-c:v",
                "hevc_vaapi",
                "-rc_mode",
                "ICQ",
                "-global_quality",
                str(quality),
            ]
        case TranscodeProfile.X265_SOFTWARE:
            # The script's settings, verbatim (download_video.sh, --postprocessor-args).
            return ["-c:v", "libx265", "-preset", "medium", "-crf", str(quality)]
        case _:
            raise ValueError(f"{profile} is not a transcode profile")


def quality_for(profile: TranscodeProfile, configured: dict[str, int] | None = None) -> int:
    """The stored value for this profile, or §4.1's default when nothing is stored."""
    stored = (configured or {}).get(str(profile))
    return int(stored) if stored else DEFAULT_QUALITY[profile]


def temp_output(job_dir: Path, container: str) -> Path:
    """Where the transcode writes before it replaces the source (§6.1)."""
    return job_dir / f"{TEMP_STEM}.{container}"


def marker(job_dir: Path) -> Path:
    return job_dir / DONE_MARKER


def build_argv(
    profile: TranscodeProfile,
    source: Path,
    output: Path,
    *,
    container: str,
    quality: int,
) -> list[str]:
    """The ffmpeg arguments (without the binary) for one transcode (§4.1)."""
    return [
        *BASE_ARGS,
        *input_args(profile),
        "-i",
        str(source),
        *MAP_ARGS,
        *video_args(profile, quality),
        *AUDIO_ARGS,
        *(MP4_ARGS if container == "mp4" else []),
        str(output),
    ]
