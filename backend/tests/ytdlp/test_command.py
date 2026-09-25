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


# ------------------------------- AC1/AC2/AC4/AC6: the M10a flags, absent unless asked for

NEW_FLAGS = [
    "--write-subs",
    "--write-auto-subs",
    "--embed-subs",
    "--convert-subs",
    "--sub-langs",
    "--sponsorblock-mark",
    "--sponsorblock-remove",
    "--limit-rate",
]


def _options_argv(**overrides: object) -> list[str]:
    options = DownloadOptions.model_validate({"quality": "1080p", **overrides})
    return build_argv(
        "https://example.test/v",
        options,
        Resolved(stream_type="dash", fragments=4, use_aria2c=False),
        job_dir=JOB_DIR,
        js_runtime="deno",
    )


def _between(argv: list[str], start: str, end: str) -> list[str]:
    return argv[argv.index(start) : argv.index(end)]


def test_default_options_add_no_new_option_flags() -> None:
    argv = _options_argv()

    assert [flag for flag in NEW_FLAGS if flag in argv] == []


@pytest.mark.parametrize(
    ("subtitles", "expected"),
    [
        (
            {"mode": "embed", "languages": ["en"]},
            ["--write-subs", "--sub-langs", "en", "--embed-subs"],
        ),
        (
            {"mode": "sidecar", "languages": ["en"]},
            ["--write-subs", "--sub-langs", "en", "--convert-subs", "srt"],
        ),
        (
            {"mode": "embed", "languages": ["en", "pt-BR"], "include_auto_captions": True},
            ["--write-subs", "--sub-langs", "en,pt-BR", "--write-auto-subs", "--embed-subs"],
        ),
        (
            {"mode": "sidecar", "languages": ["de"], "include_auto_captions": True},
            ["--write-subs", "--sub-langs", "de", "--write-auto-subs", "--convert-subs", "srt"],
        ),
    ],
    ids=["embed", "sidecar", "embed-auto-two-langs", "sidecar-auto"],
)
def test_subtitle_flags(subtitles: dict[str, object], expected: list[str]) -> None:
    argv = _options_argv(subtitles=subtitles)

    assert _between(argv, "--write-subs", "--remux-video") == expected


@pytest.mark.parametrize(
    ("sponsorblock", "expected"),
    [
        ({"mode": "mark"}, ["--sponsorblock-mark", "all"]),
        ({"mode": "remove"}, ["--sponsorblock-remove", "sponsor,selfpromo,interaction"]),
        (
            {"mode": "mark", "categories": ["intro", "outro"]},
            ["--sponsorblock-mark", "intro,outro"],
        ),
        ({"mode": "remove", "categories": ["filler"]}, ["--sponsorblock-remove", "filler"]),
    ],
    ids=["mark-default", "remove-default", "mark-picked", "remove-picked"],
)
def test_sponsorblock_flags(sponsorblock: dict[str, object], expected: list[str]) -> None:
    argv = _options_argv(sponsorblock=sponsorblock)

    assert _between(argv, expected[0], "--remux-video") == expected


def test_rate_limit_flag() -> None:
    argv = _options_argv(rate_limit="5M")

    assert argv[argv.index("--limit-rate") : argv.index("--limit-rate") + 2] == [
        "--limit-rate",
        "5M",
    ]
    assert "--limit-rate" not in _options_argv()


@pytest.mark.parametrize(
    ("overrides", "dropped"),
    [
        ({"embed_metadata": False}, "--embed-metadata"),
        ({"embed_chapters": False}, "--embed-chapters"),
    ],
    ids=["metadata", "chapters"],
)
def test_embed_toggles_only_drop_their_own_flag(overrides: dict[str, object], dropped: str) -> None:
    argv = _options_argv(**overrides)

    assert dropped not in argv
    assert len(argv) == len(_options_argv()) - 1
