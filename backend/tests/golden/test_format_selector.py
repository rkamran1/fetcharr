"""Golden parity with `get_format_selector` in download_video.sh (frozen reference)."""

import pytest

from app.ytdlp.formats import build_selector
from app.ytdlp.schemas import Container, Quality

EXPECTED: dict[tuple[Quality, Container], str] = {
    ("144p", "mkv"): "bv*[height<=144]+ba/b[height<=144]",
    ("240p", "mkv"): "bv*[height<=240]+ba/b[height<=240]",
    ("360p", "mkv"): "bv*[height<=360]+ba/b[height<=360]",
    ("480p", "mkv"): "bv*[height<=480]+ba/b[height<=480]",
    ("720p", "mkv"): "bv*[height<=720]+ba/b[height<=720]",
    ("1080p", "mkv"): "bv*[height<=1080]+ba/b[height<=1080]",
    ("1440p", "mkv"): "bv*[height<=1440]+ba/b[height<=1440]",
    ("2160p", "mkv"): "bv*[height<=2160]+ba/b[height<=2160]",
    ("4k", "mkv"): "bv*[height<=2160]+ba/b[height<=2160]",
    ("best", "mkv"): "bv*+ba/b",
    ("144p", "mp4"): (
        "bv*[height<=144][vcodec^=avc1]+ba[ext=m4a]/bv*[height<=144][ext=mp4]+ba[ext=m4a]"
        "/bv*[height<=144]+ba/b[height<=144]"
    ),
    ("240p", "mp4"): (
        "bv*[height<=240][vcodec^=avc1]+ba[ext=m4a]/bv*[height<=240][ext=mp4]+ba[ext=m4a]"
        "/bv*[height<=240]+ba/b[height<=240]"
    ),
    ("360p", "mp4"): (
        "bv*[height<=360][vcodec^=avc1]+ba[ext=m4a]/bv*[height<=360][ext=mp4]+ba[ext=m4a]"
        "/bv*[height<=360]+ba/b[height<=360]"
    ),
    ("480p", "mp4"): (
        "bv*[height<=480][vcodec^=avc1]+ba[ext=m4a]/bv*[height<=480][ext=mp4]+ba[ext=m4a]"
        "/bv*[height<=480]+ba/b[height<=480]"
    ),
    ("720p", "mp4"): (
        "bv*[height<=720][vcodec^=avc1]+ba[ext=m4a]/bv*[height<=720][ext=mp4]+ba[ext=m4a]"
        "/bv*[height<=720]+ba/b[height<=720]"
    ),
    ("1080p", "mp4"): (
        "bv*[height<=1080][vcodec^=avc1]+ba[ext=m4a]/bv*[height<=1080][ext=mp4]+ba[ext=m4a]"
        "/bv*[height<=1080]+ba/b[height<=1080]"
    ),
    ("1440p", "mp4"): (
        "bv*[height<=1440][vcodec^=avc1]+ba[ext=m4a]/bv*[height<=1440][ext=mp4]+ba[ext=m4a]"
        "/bv*[height<=1440]+ba/b[height<=1440]"
    ),
    ("2160p", "mp4"): (
        "bv*[height<=2160][vcodec^=avc1]+ba[ext=m4a]/bv*[height<=2160][ext=mp4]+ba[ext=m4a]"
        "/bv*[height<=2160]+ba/b[height<=2160]"
    ),
    ("4k", "mp4"): (
        "bv*[height<=2160][vcodec^=avc1]+ba[ext=m4a]/bv*[height<=2160][ext=mp4]+ba[ext=m4a]"
        "/bv*[height<=2160]+ba/b[height<=2160]"
    ),
    ("best", "mp4"): "bv*[vcodec^=avc1]+ba[ext=m4a]/bv*[ext=mp4]+ba[ext=m4a]/bv*+ba/b",
}


@pytest.mark.parametrize(
    ("quality", "container"), list(EXPECTED), ids=[f"{q}-{c}" for q, c in EXPECTED]
)
def test_build_selector_matches_script(quality: Quality, container: Container) -> None:
    assert build_selector(quality, container) == EXPECTED[(quality, container)]
