from typing import Any

import pytest

from app.ytdlp.schemas import DownloadOptions
from app.ytdlp.stream import Resolved, StreamType, classify, resolve_auto


def _merged(*formats: dict[str, Any]) -> dict[str, Any]:
    return {
        "protocol": "+".join(f["protocol"] for f in formats),
        "requested_formats": list(formats),
    }


@pytest.mark.parametrize(
    ("info_json", "expected"),
    [
        (_merged({"protocol": "m3u8_native"}, {"protocol": "m3u8_native"}), "hls"),
        ({"protocol": "m3u8"}, "hls"),
        (_merged({"protocol": "http_dash_segments"}, {"protocol": "http_dash_segments"}), "dash"),
        ({"protocol": "http_dash_segments_generator"}, "dash"),
        (
            _merged(
                {"protocol": "https", "container": "mp4_dash"},
                {"protocol": "https", "container": "m4a_dash"},
            ),
            "dash",
        ),
        (_merged({"protocol": "https"}, {"protocol": "https"}), "http"),
        ({"protocol": "http"}, "http"),
        ({"protocol": "https", "container": "mp4"}, "http"),
        ({}, "http"),
    ],
    ids=[
        "m3u8_native",
        "m3u8",
        "http_dash_segments",
        "http_dash_segments_generator",
        "youtube_dash_container",
        "https_merged",
        "http_single",
        "https_single",
        "no_protocol",
    ],
)
def test_classify(info_json: dict[str, Any], expected: StreamType) -> None:
    assert classify(info_json) == expected


def test_classify_hls_wins_over_dash() -> None:
    info_json = _merged({"protocol": "http_dash_segments"}, {"protocol": "m3u8_native"})

    assert classify(info_json) == "hls"


@pytest.mark.parametrize(("stream_type", "expected"), [("hls", 4), ("dash", 4), ("http", 1)])
def test_resolve_auto_fragments(stream_type: StreamType, expected: int) -> None:
    resolved = resolve_auto(stream_type, DownloadOptions(quality="best"), aria2c_available=True)

    assert resolved.fragments == expected
    assert resolved.stream_type == stream_type


@pytest.mark.parametrize(
    ("stream_type", "use_aria2c", "available", "expected"),
    [
        ("http", "auto", True, True),
        ("http", "auto", False, False),
        ("hls", "auto", True, False),
        ("dash", "auto", True, False),
        ("http", True, True, True),
        ("http", True, False, False),
        ("hls", True, True, True),
        ("hls", True, False, False),
        ("http", False, True, False),
        ("dash", False, True, False),
    ],
)
def test_resolve_auto_aria2c(
    stream_type: StreamType, use_aria2c: bool | str, available: bool, expected: bool
) -> None:
    options = DownloadOptions.model_validate({"quality": "best", "use_aria2c": use_aria2c})

    assert resolve_auto(stream_type, options, available).use_aria2c is expected


@pytest.mark.parametrize("stream_type", ["hls", "dash", "http"])
def test_resolve_keeps_explicit_fragments(stream_type: StreamType) -> None:
    options = DownloadOptions(quality="best", fragments=7)

    assert resolve_auto(stream_type, options, aria2c_available=False) == Resolved(
        stream_type=stream_type, fragments=7, use_aria2c=False
    )
