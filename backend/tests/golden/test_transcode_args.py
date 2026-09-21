"""Golden parity with the transcode half of download_video.sh (frozen reference).

The script builds one `--postprocessor-args` string per container (lines 454-462):

    mp4: ffmpeg:-c:v libx265 -preset medium -crf 23 -tag:v hvc1 -c:a aac -b:a 128k
         -movflags +faststart
    mkv: ffmpeg:-c:v libx265 -preset medium -crf 23 -c:a aac -b:a 128k

M7 moves that out of the yt-dlp argv into its own ffmpeg step (§4.1), so the settings are
grouped differently, but every flag the script passed is still passed, unchanged. Only a plan
that explicitly changes this behaviour may touch the expectations below.
"""

from pathlib import Path

from app.transcode.profiles import (
    AUDIO_ARGS,
    DEFAULT_QUALITY,
    MP4_ARGS,
    TranscodeProfile,
    build_argv,
    video_args,
)

JOB_DIR = Path("/data/incomplete/42")
SOURCE_MKV = JOB_DIR / "dQw4w9WgXcQ.mkv"
SOURCE_MP4 = JOB_DIR / "dQw4w9WgXcQ.mp4"

#: `-progress`/`-nostats` are fetcharr's additions (§4.1); the script parsed nothing.
FETCHARR_ADDITIONS = [
    "-nostdin",
    "-hide_banner",
    "-loglevel",
    "error",
    "-progress",
    "pipe:1",
    "-nostats",
    "-y",
]
#: `-map 0` with subtitle and chapter copy (§4.1).
MAP = ["-map", "0", "-c:s", "copy", "-map_chapters", "0"]


def test_x265_software_video_args_match_the_script() -> None:
    assert video_args(TranscodeProfile.X265_SOFTWARE, 23) == [
        "-c:v",
        "libx265",
        "-preset",
        "medium",
        "-crf",
        "23",
    ]


def test_the_x265_default_quality_is_the_scripts_crf() -> None:
    assert DEFAULT_QUALITY[TranscodeProfile.X265_SOFTWARE] == 23


def test_mp4_extras_match_the_script() -> None:
    assert MP4_ARGS == ["-tag:v", "hvc1", "-movflags", "+faststart"]


def test_shared_audio_args_match_the_script() -> None:
    assert AUDIO_ARGS == ["-c:a", "aac", "-b:a", "128k"]


def test_full_x265_argv_mkv() -> None:
    argv = build_argv(
        TranscodeProfile.X265_SOFTWARE,
        SOURCE_MKV,
        JOB_DIR / "transcoded.tmp.mkv",
        container="mkv",
        quality=23,
    )

    assert argv == [
        *FETCHARR_ADDITIONS,
        "-i",
        "/data/incomplete/42/dQw4w9WgXcQ.mkv",
        *MAP,
        "-c:v",
        "libx265",
        "-preset",
        "medium",
        "-crf",
        "23",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "/data/incomplete/42/transcoded.tmp.mkv",
    ]


def test_full_x265_argv_mp4() -> None:
    argv = build_argv(
        TranscodeProfile.X265_SOFTWARE,
        SOURCE_MP4,
        JOB_DIR / "transcoded.tmp.mp4",
        container="mp4",
        quality=23,
    )

    assert argv == [
        *FETCHARR_ADDITIONS,
        "-i",
        "/data/incomplete/42/dQw4w9WgXcQ.mp4",
        *MAP,
        "-c:v",
        "libx265",
        "-preset",
        "medium",
        "-crf",
        "23",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-tag:v",
        "hvc1",
        "-movflags",
        "+faststart",
        "/data/incomplete/42/transcoded.tmp.mp4",
    ]
