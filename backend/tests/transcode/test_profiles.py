"""The hardware profiles' argv and the quality values behind them (requirements §4.1)."""

from pathlib import Path

import pytest

from app.transcode.profiles import (
    AUDIO_ARGS,
    DEFAULT_QUALITY,
    MAP_ARGS,
    MP4_ARGS,
    TranscodeProfile,
    build_argv,
    marker,
    quality_for,
    temp_output,
    video_args,
)

JOB_DIR = Path("/data/incomplete/42")
SOURCE = JOB_DIR / "dQw4w9WgXcQ.mkv"

HARDWARE_PROFILES = [TranscodeProfile.HEVC_QSV, TranscodeProfile.HEVC_VAAPI]


def _argv(profile: TranscodeProfile, container: str = "mkv", quality: int = 24) -> list[str]:
    return build_argv(
        profile,
        SOURCE,
        temp_output(JOB_DIR, container),
        container=container,
        quality=quality,
    )


def test_qsv_argv_matches_the_requirements() -> None:
    argv = _argv(TranscodeProfile.HEVC_QSV)
    before_input = argv[: argv.index("-i")]
    after_input = argv[argv.index("-i") + 2 :]

    # The device setup flags only work before `-i` (§4.1).
    assert before_input[-8:] == [
        "-init_hw_device",
        "qsv=hw",
        "-filter_hw_device",
        "hw",
        "-hwaccel",
        "qsv",
        "-hwaccel_output_format",
        "qsv",
    ]
    assert after_input[: len(MAP_ARGS)] == MAP_ARGS
    assert after_input[len(MAP_ARGS) :] == [
        "-c:v",
        "hevc_qsv",
        "-preset",
        "medium",
        "-global_quality",
        "24",
        "-look_ahead",
        "1",
        *AUDIO_ARGS,
        "/data/incomplete/42/transcoded.tmp.mkv",
    ]


def test_vaapi_argv_matches_the_requirements() -> None:
    argv = _argv(TranscodeProfile.HEVC_VAAPI)
    before_input = argv[: argv.index("-i")]
    after_input = argv[argv.index("-i") + 2 :]

    assert before_input[-2:] == ["-vaapi_device", "/dev/dri/renderD128"]
    assert after_input[len(MAP_ARGS) :] == [
        "-vf",
        "format=nv12,hwupload",
        "-c:v",
        "hevc_vaapi",
        "-rc_mode",
        "ICQ",
        "-global_quality",
        "24",
        *AUDIO_ARGS,
        "/data/incomplete/42/transcoded.tmp.mkv",
    ]


@pytest.mark.parametrize("profile", HARDWARE_PROFILES)
def test_quality_comes_from_the_caller(profile: TranscodeProfile) -> None:
    argv = _argv(profile, quality=18)

    assert "18" in argv
    assert argv[argv.index("-global_quality") + 1] == "18"


@pytest.mark.parametrize("profile", [*HARDWARE_PROFILES, TranscodeProfile.X265_SOFTWARE])
@pytest.mark.parametrize("container", ["mkv", "mp4"])
def test_output_is_the_temp_file_next_to_the_source(
    profile: TranscodeProfile, container: str
) -> None:
    argv = _argv(profile, container=container)

    assert argv[-1] == f"/data/incomplete/42/transcoded.tmp.{container}"
    assert temp_output(JOB_DIR, container).parent == SOURCE.parent


@pytest.mark.parametrize("profile", HARDWARE_PROFILES)
def test_mp4_extras_are_added_only_for_mp4(profile: TranscodeProfile) -> None:
    assert _argv(profile, container="mp4")[-5:-1] == MP4_ARGS
    assert not set(MP4_ARGS) & set(_argv(profile, container="mkv"))


def test_defaults_are_24_24_23() -> None:
    assert DEFAULT_QUALITY == {
        TranscodeProfile.HEVC_QSV: 24,
        TranscodeProfile.HEVC_VAAPI: 24,
        TranscodeProfile.X265_SOFTWARE: 23,
    }


def test_quality_for_prefers_what_is_configured() -> None:
    configured = {"hevc-qsv": 20}

    assert quality_for(TranscodeProfile.HEVC_QSV, configured) == 20
    assert quality_for(TranscodeProfile.X265_SOFTWARE, configured) == 23
    assert quality_for(TranscodeProfile.HEVC_VAAPI, None) == 24


def test_off_is_not_an_encoder() -> None:
    with pytest.raises(ValueError, match="not a transcode profile"):
        video_args(TranscodeProfile.OFF, 24)


def test_the_marker_lives_in_the_job_dir() -> None:
    assert marker(JOB_DIR) == JOB_DIR / "transcode.done"
