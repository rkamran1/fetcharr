import asyncio
import os

import pytest

from app.ytdlp import inspect
from app.ytdlp.inspect import (
    ErrorKind,
    YtdlpError,
    build_inspect_argv,
    classify_error,
    run_json,
)
from tests.fake_ytdlp import FIXTURES, FakeYtdlp


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


@pytest.mark.parametrize(
    ("fixture", "kind", "message"),
    [
        ("private.txt", "needs_cookies", None),
        ("age.txt", "needs_cookies", None),
        ("members_only.txt", "needs_cookies", None),
        ("bot_check.txt", "needs_cookies", None),
        ("login_required.txt", "needs_cookies", None),
        ("unsupported.txt", "unsupported", "Unsupported URL"),
        ("unavailable.txt", "unavailable", "This video is unavailable"),
        ("not_found.txt", "unavailable", "Not found."),
        (
            "removed.txt",
            "unavailable",
            "This video may be deleted or geo-restricted. "
            "You might want to try a VPN or a proxy server (with --proxy)",
        ),
        ("network.txt", "failed", None),
    ],
)
def test_error_mapping(fixture: str, kind: ErrorKind, message: str | None) -> None:
    stderr = _stderr(fixture)

    error = classify_error(stderr)

    assert error.kind == kind
    if message is not None:
        assert error.message == message
    if kind == "failed":
        assert error.message == stderr.strip().splitlines()[-1]
    if kind == "needs_cookies":
        assert not error.message.startswith(("ERROR", "["))


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

    with pytest.raises(YtdlpError) as caught:
        await run_json(build_inspect_argv("https://www.dailymotion.com/video/x3z49k", None))

    assert caught.value.kind == "timeout"
    stub, grandchild = fake_ytdlp.pids()
    assert _gone(stub)
    for _ in range(50):
        if _gone(grandchild):
            break
        await asyncio.sleep(0.1)
    assert _gone(grandchild)
