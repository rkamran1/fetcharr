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
