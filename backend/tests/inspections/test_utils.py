import json
from typing import Any

import pytest

from app.inspections.exceptions import InspectError
from app.inspections.utils import PLAYLIST_MESSAGE, normalise
from tests.fake_ytdlp import FIXTURES


def _fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text())


def test_normalise_youtube() -> None:
    info = normalise(_fixture("youtube.json"), aria2c_available=True)

    assert info["title"] == "Big Buck Bunny 60fps 4K - Official Blender Foundation Short Film"
    assert info["uploader"] == "Blender"
    assert info["thumbnail"] == "https://i.ytimg.com/vi_webp/aqz-KE-bpKQ/maxresdefault.webp"
    assert info["duration"] == 635
    assert info["webpage_url"] == "https://www.youtube.com/watch?v=aqz-KE-bpKQ"
    assert info["extractor"] == "youtube"
    assert info["id"] == "aqz-KE-bpKQ"
    assert info["upload_date"] == "20141110"
    assert info["release_year"] == 2014
    assert info["video_heights"] == [2160, 1440, 1080, 720, 480, 360, 240, 144]
    assert info["video_codecs"] == ["av01", "avc1", "vp9"]
    assert {"lang": None, "codec": "mp4a", "abr": 129} in info["audio_tracks"]
    assert {"lang": None, "codec": "opus", "abr": 129} in info["audio_tracks"]
    assert info["has_hdr"] is False
    # Largest 2160p video (VP9 315) plus the largest audio-only format (m4a 140). A
    # reported size always wins over a bitrate estimate (M5a).
    assert info["estimated_sizes"]["2160"] == 1362269481 + 10271496
    assert list(info["estimated_sizes"]) == [str(h) for h in info["video_heights"]]
    assert info["stream_type"] == "dash"
    assert info["auto"] == {"fragments": 4, "use_aria2c": False}


def test_normalise_youtube_subtitles() -> None:
    info = normalise(_fixture("youtube_subtitles.json"), aria2c_available=False)

    assert info["subtitles"]["en"] == ["json3", "srv1", "srv2", "srv3", "ttml", "srt", "vtt"]
    assert set(info["subtitles"]) == {"en", "de"}
    assert info["automatic_captions"] == {"en": ["vtt"], "de": ["vtt"]}


def test_normalise_dailymotion_is_hls_with_four_fragments() -> None:
    info = normalise(_fixture("dailymotion.json"), aria2c_available=True)

    assert info["stream_type"] == "hls"
    assert info["auto"] == {"fragments": 4, "use_aria2c": False}
    assert info["video_heights"] == [576, 480, 384]
    # Muxed HLS formats: the audio comes from them, and none reports a filesize, so the
    # sizes are estimated from the bitrate over the 106 s running time (M5a).
    assert info["audio_tracks"] == [{"lang": None, "codec": "mp4a", "abr": None}]
    assert info["estimated_sizes"] == {"576": 28_477_960, "480": 11_080_710, "384": 6_102_420}


def test_normalise_bilibili_is_http() -> None:
    info = normalise(_fixture("bilibili.json"), aria2c_available=True)

    # Plain https video-only + audio-only formats, no DASH container (owner decision, M4).
    assert info["stream_type"] == "http"
    assert info["auto"] == {"fragments": 1, "use_aria2c": True}
    assert info["video_heights"] == [1080, 720, 480, 360]


def test_normalise_rejects_playlist() -> None:
    with pytest.raises(InspectError) as caught:
        normalise(_fixture("playlist.json"), aria2c_available=False)

    assert (caught.value.status, caught.value.detail) == (422, PLAYLIST_MESSAGE)


def test_normalise_estimates_a_size_from_the_bitrate() -> None:
    """Formats with no filesize still get a size, so every height shows one (M5a)."""
    info = normalise(
        {
            "id": "x",
            "title": "x",
            "duration": 100,
            "formats": [
                {"height": 720, "vcodec": "avc1", "acodec": "none", "tbr": 800},
                {"height": 360, "vcodec": "avc1", "acodec": "none", "tbr": 400, "filesize": 1000},
                {"height": 240, "vcodec": "avc1", "acodec": "none"},
                {"vcodec": "none", "acodec": "mp4a", "tbr": 128},
            ],
        },
        aria2c_available=False,
    )

    # 800 kbit/s video + 128 kbit/s audio over 100 s.
    assert info["estimated_sizes"]["720"] == 800 * 1000 // 8 * 100 + 128 * 1000 // 8 * 100
    # A reported filesize is used as it stands, plus the largest known audio size.
    assert info["estimated_sizes"]["360"] == 1000
    # Neither a size nor a bitrate: no guess at all.
    assert "240" not in info["estimated_sizes"]
