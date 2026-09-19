import asyncio
import json
import os
from typing import Any

import pytest

from app.ytdlp import inspect
from app.ytdlp.inspect import (
    PLAYLIST_MESSAGE,
    InspectError,
    build_inspect_argv,
    classify_error,
    normalise,
    run_inspect,
)
from tests.fake_ytdlp import FIXTURES, FakeYtdlp


def _fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text())


def _stderr(name: str) -> str:
    return (FIXTURES / "stderr" / name).read_text()


def test_argv_youtube() -> None:
    url = "https://www.youtube.com/watch?v=aqz-KE-bpKQ&list=PL123"

    assert build_inspect_argv(url, "deno") == [
        "-J",
        "--no-download",
        "--no-playlist",
        "--remote-components",
        "ejs:github",
        url,
    ]


def test_argv_youtube_with_node() -> None:
    url = "https://youtu.be/aqz-KE-bpKQ"

    assert build_inspect_argv(url, "node") == [
        "-J",
        "--no-download",
        "--no-playlist",
        "--remote-components",
        "ejs:github",
        "--js-runtimes",
        "node",
        url,
    ]


def test_argv_other_site() -> None:
    url = "https://www.dailymotion.com/video/x3z49k"

    assert build_inspect_argv(url, "node") == ["-J", "--no-download", "--no-playlist", url]


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
    # Largest 2160p video (VP9 315) plus the largest audio-only format (m4a 140).
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
    # Muxed HLS formats: the audio comes from them, and no sizes are known.
    assert info["audio_tracks"] == [{"lang": None, "codec": "mp4a", "abr": None}]
    assert info["estimated_sizes"] == {}


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


@pytest.mark.parametrize(
    ("fixture", "status", "needs_cookies", "detail"),
    [
        ("private.txt", 422, True, None),
        ("age.txt", 422, True, None),
        ("members_only.txt", 422, True, None),
        ("bot_check.txt", 422, True, None),
        ("login_required.txt", 422, True, None),
        ("unsupported.txt", 422, False, "Unsupported URL"),
        ("unavailable.txt", 422, False, "This video is unavailable"),
        ("not_found.txt", 422, False, "Not found."),
        (
            "removed.txt",
            422,
            False,
            "This video may be deleted or geo-restricted. "
            "You might want to try a VPN or a proxy server (with --proxy)",
        ),
        ("network.txt", 502, False, None),
    ],
)
def test_error_mapping(fixture: str, status: int, needs_cookies: bool, detail: str | None) -> None:
    stderr = _stderr(fixture)

    error = classify_error(stderr)

    assert (error.status, error.needs_cookies) == (status, needs_cookies)
    if detail is not None:
        assert error.detail == detail
    if status == 502:
        assert error.detail == stderr.strip().splitlines()[-1]
    if needs_cookies:
        assert not error.detail.startswith(("ERROR", "["))


def _gone(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return False


async def test_timeout_kills_process_group(
    fake_ytdlp: FakeYtdlp, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(inspect, "INSPECT_TIMEOUT_S", 1.0)
    fake_ytdlp.hangs()

    with pytest.raises(InspectError) as caught:
        await run_inspect("https://www.dailymotion.com/video/x3z49k", None, False)

    assert caught.value.status == 504
    stub, grandchild = fake_ytdlp.pids()
    assert _gone(stub)
    for _ in range(50):
        if _gone(grandchild):
            break
        await asyncio.sleep(0.1)
    assert _gone(grandchild)
