import inspect
from pathlib import Path

import pytest

from app.ytdlp.command import build_argv, downgrade_fragments
from app.ytdlp.schemas import Container, DownloadOptions
from app.ytdlp.stream import Resolved, StreamType

JOB_DIR = Path("/data/incomplete/7")


def _argv(
    url: str = "https://example.test/v",
    *,
    container: Container = "mkv",
    stream_type: StreamType = "dash",
) -> list[str]:
    return build_argv(
        url,
        DownloadOptions(quality="1080p", container=container),
        Resolved(stream_type=stream_type, fragments=4, use_aria2c=False),
        job_dir=JOB_DIR,
        js_runtime="deno",
    )


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://youtube.com/watch?v=abc", True),
        ("https://www.youtube.com/watch?v=abc", True),
        ("https://m.youtube.com/watch?v=abc", True),
        ("https://music.youtube.com/watch?v=abc", True),
        ("https://youtu.be/abc", True),
        ("https://WWW.YouTube.com/watch?v=abc", True),
        ("https://notyoutube.com/watch?v=abc", False),
        ("https://youtube.com.evil.test/watch?v=abc", False),
        ("https://evil.test/?u=youtube.com", False),
        ("https://youtu.be.evil.test/abc", False),
    ],
)
def test_remote_components_only_for_youtube_hosts(url: str, expected: bool) -> None:
    argv = _argv(url)

    assert ("--remote-components" in argv) is expected
    if expected:
        i = argv.index("--remote-components")
        assert argv[i + 1] == "ejs:github"


@pytest.mark.parametrize("container", ["mkv", "mp4"])
@pytest.mark.parametrize("stream_type", ["hls", "dash", "http"])
def test_always_remux_never_recode(container: Container, stream_type: StreamType) -> None:
    argv = _argv(container=container, stream_type=stream_type)

    assert argv.count("--remux-video") == 1
    assert argv[argv.index("--remux-video") + 1] == container
    assert "--recode-video" not in argv
    assert "--postprocessor-args" not in argv


def test_rejects_url_starting_with_dash() -> None:
    with pytest.raises(ValueError):
        _argv("--exec=touch /tmp/pwned")


def test_build_argv_has_no_passthrough_parameter() -> None:
    params = inspect.signature(build_argv).parameters

    assert list(params) == ["url", "options", "resolved", "job_dir", "cookies_path", "js_runtime"]


def test_downgrade_fragments_only_changes_fragment_count() -> None:
    argv = _argv()
    original = list(argv)

    downgraded = downgrade_fragments(argv)

    i = argv.index("--concurrent-fragments")
    assert argv[i + 1] == "4"
    assert downgraded[i + 1] == "1"
    assert downgraded[: i + 1] == argv[: i + 1]
    assert downgraded[i + 2 :] == argv[i + 2 :]
    assert argv == original


# ------------------------------------------- AC10: the selector variant for transcoding


def _selector(transcode: str, container: Container = "mkv") -> str:
    argv = build_argv(
        "https://example.test/v",
        DownloadOptions(quality="1080p", container=container, transcode=transcode),
        Resolved(stream_type="dash", fragments=4, use_aria2c=False),
        job_dir=JOB_DIR,
        js_runtime="deno",
    )
    return argv[argv.index("--format") + 1]


def test_selector_is_unchanged_when_transcoding_is_off() -> None:
    """AC15: an untouched download builds exactly the argv M2 froze."""
    assert _selector("off") == "bv*[height<=1080]+ba/b[height<=1080]"
    assert _selector("off", "mp4") == (
        "bv*[height<=1080][vcodec^=avc1]+ba[ext=m4a]/bv*[height<=1080][ext=mp4]+ba[ext=m4a]"
        "/bv*[height<=1080]+ba/b[height<=1080]"
    )


def test_selector_prefers_gpu_decodable_codecs_when_transcoding() -> None:
    """The UHD 630 decodes H.264 and VP9 but not AV1, so those come first (§4.1)."""
    assert _selector("hevc-qsv") == (
        "bv*[height<=1080][vcodec^=avc1]+ba"
        "/bv*[height<=1080][vcodec^=vp9]+ba"
        "/bv*[height<=1080]+ba/b[height<=1080]"
    )


def test_the_transcode_selector_keeps_the_m4a_preference_for_mp4() -> None:
    assert _selector("x265-software", "mp4") == (
        "bv*[height<=1080][vcodec^=avc1]+ba[ext=m4a]"
        "/bv*[height<=1080][vcodec^=vp9]+ba[ext=m4a]"
        "/bv*[height<=1080][vcodec^=avc1]+ba[ext=m4a]/bv*[height<=1080][ext=mp4]+ba[ext=m4a]"
        "/bv*[height<=1080]+ba/b[height<=1080]"
    )


def test_transcoding_still_remuxes_and_changes_nothing_else() -> None:
    """The download argv always takes the remux path; the transcode is its own step (§4)."""
    plain = build_argv(
        "https://example.test/v",
        DownloadOptions(quality="1080p"),
        Resolved(stream_type="dash", fragments=4, use_aria2c=False),
        job_dir=JOB_DIR,
        js_runtime="deno",
    )
    transcoded = build_argv(
        "https://example.test/v",
        DownloadOptions(quality="1080p", transcode="hevc-qsv", transcode_quality=20),
        Resolved(stream_type="dash", fragments=4, use_aria2c=False),
        job_dir=JOB_DIR,
        js_runtime="deno",
    )

    assert "--remux-video" in transcoded
    assert "--recode-video" not in transcoded
    # The selector is the only difference: no transcode flag ever reaches yt-dlp.
    assert transcoded[:1] + transcoded[2:] == plain[:1] + plain[2:]
