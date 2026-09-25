"""AC5: the M10a selector variants. The script's own selector stays the last alternative.

The frozen (quality x container) strings live in `tests/golden/test_format_selector.py`; this
file only covers what the new preferences prepend to them.
"""

from typing import TypedDict

import pytest

from app.ytdlp.formats import build_selector
from app.ytdlp.schemas import Container, Quality, VideoCodec

PLAIN_1080_MKV = "bv*[height<=1080]+ba/b[height<=1080]"


@pytest.mark.parametrize(
    ("codec", "expected"),
    [
        ("h264", "bv*[height<=1080][vcodec^=avc1]+ba"),
        ("vp9", "bv*[height<=1080][vcodec^=vp9]+ba"),
        ("av1", "bv*[height<=1080][vcodec^=av01]+ba"),
    ],
)
def test_codec_preference_variants(codec: VideoCodec, expected: str) -> None:
    selector = build_selector("1080p", "mkv", video_codec=codec)

    assert selector == f"{expected}/{PLAIN_1080_MKV}"


def test_audio_language_variant() -> None:
    selector = build_selector("1080p", "mkv", audio_language="en")

    assert selector == f"bv*[height<=1080]+ba[language=en]/{PLAIN_1080_MKV}"


def test_hdr_off_variant() -> None:
    selector = build_selector("1080p", "mkv", allow_hdr=False)

    assert selector == f"bv*[height<=1080][dynamic_range=SDR]+ba/{PLAIN_1080_MKV}"


def test_combined_variant() -> None:
    selector = build_selector(
        "1080p", "mkv", video_codec="h264", audio_language="pt-BR", allow_hdr=False
    )

    assert selector == (
        f"bv*[height<=1080][vcodec^=avc1][dynamic_range=SDR]+ba[language=pt-BR]/{PLAIN_1080_MKV}"
    )


def test_mp4_keeps_its_m4a_audio_preference() -> None:
    selector = build_selector("720p", "mp4", audio_language="en")

    assert selector.startswith("bv*[height<=720]+ba[ext=m4a][language=en]/")


def test_best_has_no_height_filter() -> None:
    selector = build_selector("best", "mkv", video_codec="av1")

    assert selector == "bv*[vcodec^=av01]+ba/bv*+ba/b"


def test_gpu_decode_still_works_and_an_explicit_codec_wins() -> None:
    gpu = build_selector("1080p", "mkv", prefer_gpu_decode=True)
    assert gpu == (
        f"bv*[height<=1080][vcodec^=avc1]+ba/bv*[height<=1080][vcodec^=vp9]+ba/{PLAIN_1080_MKV}"
    )

    picked = build_selector("1080p", "mkv", prefer_gpu_decode=True, video_codec="av1")
    assert picked == f"bv*[height<=1080][vcodec^=av01]+ba/{PLAIN_1080_MKV}"


QUALITIES: list[Quality] = ["144p", "720p", "1080p", "2160p", "best"]
CONTAINERS: list[Container] = ["mkv", "mp4"]


class Variant(TypedDict, total=False):
    prefer_gpu_decode: bool
    video_codec: VideoCodec
    audio_language: str | None
    allow_hdr: bool


VARIANTS: list[Variant] = [
    {},
    {"video_codec": "h264"},
    {"video_codec": "av1"},
    {"audio_language": "en"},
    {"allow_hdr": False},
    {"prefer_gpu_decode": True},
    {"video_codec": "vp9", "audio_language": "de", "allow_hdr": False},
    {"prefer_gpu_decode": True, "allow_hdr": False},
]


@pytest.mark.parametrize("quality", QUALITIES)
@pytest.mark.parametrize("container", CONTAINERS)
@pytest.mark.parametrize("variant", VARIANTS, ids=range(len(VARIANTS)))
def test_every_variant_ends_with_the_script_selector(
    quality: Quality, container: Container, variant: Variant
) -> None:
    plain = build_selector(quality, container)
    selector = build_selector(quality, container, **variant)

    assert selector.endswith(plain)
    assert selector == plain or selector.endswith(f"/{plain}")


@pytest.mark.parametrize("quality", QUALITIES)
@pytest.mark.parametrize("container", CONTAINERS)
def test_the_defaults_change_nothing(quality: Quality, container: Container) -> None:
    assert build_selector(
        quality,
        container,
        prefer_gpu_decode=False,
        video_codec="any",
        audio_language=None,
        allow_hdr=True,
    ) == build_selector(quality, container)
