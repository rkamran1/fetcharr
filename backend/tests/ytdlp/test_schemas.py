from typing import Any

import pytest
from pydantic import ValidationError

from app.transcode.profiles import TranscodeProfile
from app.ytdlp.schemas import DownloadOptions


def test_defaults() -> None:
    options = DownloadOptions(quality="720p")

    assert options.container == "mkv"
    assert options.fragments == "auto"
    assert options.use_aria2c == "auto"
    assert options.retries == 5


def test_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        DownloadOptions.model_validate({"quality": "720p", "exec": "rm -rf /"})


@pytest.mark.parametrize(
    "overrides",
    [
        {"fragments": 0},
        {"fragments": 17},
        {"container": "avi"},
        {"quality": "999p"},
        {"use_aria2c": "maybe"},
        {"retries": -1},
    ],
    ids=lambda o: "-".join(f"{k}={v}" for k, v in o.items()),
)
def test_rejects_invalid_values(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        DownloadOptions.model_validate({"quality": "720p", **overrides})


# ------------------------------------------- AC15: transcoding is opt-in, never automatic


def test_transcode_is_off_unless_asked_for() -> None:
    options = DownloadOptions(quality="best")

    assert options.transcode is TranscodeProfile.OFF
    assert options.transcode_quality is None


def test_a_body_that_omits_transcoding_is_a_plain_download() -> None:
    """Every request written before M7 keeps behaving exactly as it did (§5 step 2d)."""
    options = DownloadOptions.model_validate(
        {"quality": "1080p", "container": "mp4", "fragments": 4, "use_aria2c": True, "retries": 2}
    )

    assert options.transcode is TranscodeProfile.OFF


@pytest.mark.parametrize(
    "profile", ["hevc-qsv", "hevc-vaapi", "x265-software", TranscodeProfile.HEVC_QSV]
)
def test_a_picked_profile_is_kept(profile: str | TranscodeProfile) -> None:
    options = DownloadOptions.model_validate({"quality": "best", "transcode": profile})

    assert options.transcode == profile
    # Stored as a plain string, so the options blob round-trips through the JSON column.
    assert DownloadOptions(**options.model_dump()).transcode == profile


@pytest.mark.parametrize(
    "overrides", [{"transcode": "av1-qsv"}, {"transcode_quality": 0}, {"transcode_quality": 52}]
)
def test_rejects_invalid_transcode_values(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        DownloadOptions.model_validate({"quality": "720p", **overrides})
