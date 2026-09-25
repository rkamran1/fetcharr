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


# ------------------------------------- AC2/AC4/AC6: the M10a options and their allow-lists


def test_new_options_default_to_the_script_behaviour() -> None:
    options = DownloadOptions(quality="720p")

    assert options.subtitles.mode == "off"
    assert options.subtitles.languages == ()
    assert options.subtitles.include_auto_captions is False
    assert options.sponsorblock.mode == "off"
    assert options.audio_language is None
    assert options.video_codec == "any"
    assert options.allow_hdr is True
    assert options.rate_limit is None
    assert options.embed_metadata is True
    assert options.embed_chapters is True


@pytest.mark.parametrize("language", ["en", "pt-BR", "zh-Hans", "fil"])
def test_accepts_language_tags(language: str) -> None:
    options = _with(subtitles={"mode": "sidecar", "languages": [language]})

    assert options.subtitles.languages == (language,)


@pytest.mark.parametrize("language", ["en_US", "EN", "e", "../x", "", "en;rm -rf", "english-x"])
def test_rejects_a_malformed_subtitle_language(language: str) -> None:
    with pytest.raises(ValidationError):
        _with(subtitles={"mode": "sidecar", "languages": [language]})


@pytest.mark.parametrize("language", ["en_US", "EN", "", "-en"])
def test_rejects_a_malformed_audio_language(language: str) -> None:
    with pytest.raises(ValidationError):
        _with(audio_language=language)


@pytest.mark.parametrize("mode", ["embed", "sidecar"])
def test_a_subtitle_mode_needs_at_least_one_language(mode: str) -> None:
    with pytest.raises(ValidationError):
        _with(subtitles={"mode": mode, "languages": []})


def test_subtitle_languages_are_deduplicated() -> None:
    options = _with(subtitles={"mode": "embed", "languages": ["en", "de", "en"]})

    assert options.subtitles.languages == ("en", "de")


def test_rejects_a_sponsorblock_category_outside_the_allow_list() -> None:
    with pytest.raises(ValidationError):
        _with(sponsorblock={"mode": "mark", "categories": ["rm -rf"]})


def test_poi_highlight_cannot_be_removed() -> None:
    assert _with(sponsorblock={"mode": "mark", "categories": ["poi_highlight"]})

    with pytest.raises(ValidationError):
        _with(sponsorblock={"mode": "remove", "categories": ["poi_highlight"]})


def test_sponsorblock_fills_in_the_mode_default() -> None:
    assert _with(sponsorblock={"mode": "mark"}).sponsorblock.chosen() == ("all",)
    assert _with(sponsorblock={"mode": "remove"}).sponsorblock.chosen() == (
        "sponsor",
        "selfpromo",
        "interaction",
    )
    picked = _with(sponsorblock={"mode": "mark", "categories": ["intro", "outro"]})
    assert picked.sponsorblock.chosen() == ("intro", "outro")


@pytest.mark.parametrize("rate", ["500K", "5M", "1.5M", "800"])
def test_rate_limit_accepts_valid_rates(rate: str) -> None:
    assert _with(rate_limit=rate).rate_limit == rate


@pytest.mark.parametrize("rate", ["abc", "-1", "5G/s", "5 M", "0", "", "5M ", "M5"])
def test_rate_limit_rejects_invalid_rates(rate: str) -> None:
    with pytest.raises(ValidationError):
        _with(rate_limit=rate)


def test_nested_options_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        _with(subtitles={"mode": "off", "exec": "rm -rf /"})


def _with(**overrides: Any) -> DownloadOptions:
    return DownloadOptions.model_validate({"quality": "720p", **overrides})
