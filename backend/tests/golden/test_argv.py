"""Golden argv parity with the `CMD` array in download_video.sh (frozen reference).

Each expectation is the script's `CMD` (without `CMD[0]`, the `yt-dlp` binary, and without the
URL) written by hand from the script, then fetcharr's §4 additions, then the URL.
"""

from pathlib import Path

import pytest

from app.ytdlp.command import build_argv
from app.ytdlp.schemas import DownloadOptions
from app.ytdlp.stream import StreamType, resolve_auto

JOB_DIR = Path("/data/incomplete/42")

FETCHARR_ADDITIONS = [
    "--newline",
    "--progress",
    "--progress-template",
    "download:FA_PROGRESS %(progress)j",
    "--print-to-file",
    "after_move:%(filepath)s",
    "/data/incomplete/42/final_path",
    "-P",
    "home:/data/incomplete/42",
    "-P",
    "temp:/data/incomplete/42/tmp",
    "-o",
    "%(id)s.%(ext)s",
]

YOUTUBE = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
YOUTU_BE = "https://youtu.be/dQw4w9WgXcQ"
DAILYMOTION = "https://www.dailymotion.com/video/x8abc12"
PLAIN_HTTP = "https://media.example.test/clip.mp4"
VIMEO = "https://vimeo.com/76979871"

CASES = {
    "a_youtube_1080p_mkv_dash_deno": dict(
        url=YOUTUBE,
        options=DownloadOptions(quality="1080p"),
        stream_type="dash",
        aria2c_available=True,
        js_runtime="deno",
        cookies_path=None,
        script=[
            "--format",
            "bv*[height<=1080]+ba/b[height<=1080]",
            "--merge-output-format",
            "mkv",
            "--embed-chapters",
            "--embed-metadata",
            "--no-playlist",
            "--concurrent-fragments",
            "4",
            "--retries",
            "5",
            "--fragment-retries",
            "5",
            "--http-chunk-size",
            "10M",
            "--buffer-size",
            "16K",
            "--abort-on-unavailable-fragment",
            "--keep-fragments",
            "--no-check-certificates",
            "--remote-components",
            "ejs:github",
            "--remux-video",
            "mkv",
        ],
    ),
    "b_youtube_720p_mp4_node": dict(
        url=YOUTU_BE,
        options=DownloadOptions(quality="720p", container="mp4"),
        stream_type="dash",
        aria2c_available=True,
        js_runtime="node",
        cookies_path=None,
        script=[
            "--format",
            "bv*[height<=720][vcodec^=avc1]+ba[ext=m4a]/bv*[height<=720][ext=mp4]+ba[ext=m4a]"
            "/bv*[height<=720]+ba/b[height<=720]",
            "--merge-output-format",
            "mp4",
            "--embed-chapters",
            "--embed-metadata",
            "--no-playlist",
            "--concurrent-fragments",
            "4",
            "--retries",
            "5",
            "--fragment-retries",
            "5",
            "--http-chunk-size",
            "10M",
            "--buffer-size",
            "16K",
            "--abort-on-unavailable-fragment",
            "--keep-fragments",
            "--no-check-certificates",
            "--remote-components",
            "ejs:github",
            "--js-runtimes",
            "node",
            "--remux-video",
            "mp4",
        ],
    ),
    "c_hls_1080p_mkv": dict(
        url=DAILYMOTION,
        options=DownloadOptions(quality="1080p"),
        stream_type="hls",
        aria2c_available=True,
        js_runtime="deno",
        cookies_path=None,
        script=[
            "--format",
            "bv*[height<=1080]+ba/b[height<=1080]",
            "--merge-output-format",
            "mkv",
            "--embed-chapters",
            "--embed-metadata",
            "--no-playlist",
            "--concurrent-fragments",
            "4",
            "--retries",
            "5",
            "--fragment-retries",
            "5",
            "--http-chunk-size",
            "10M",
            "--buffer-size",
            "16K",
            "--abort-on-unavailable-fragment",
            "--keep-fragments",
            "--no-check-certificates",
            "--remux-video",
            "mkv",
        ],
    ),
    "d_http_mp4_aria2c": dict(
        url=PLAIN_HTTP,
        options=DownloadOptions(quality="480p", container="mp4"),
        stream_type="http",
        aria2c_available=True,
        js_runtime="deno",
        cookies_path=None,
        script=[
            "--format",
            "bv*[height<=480][vcodec^=avc1]+ba[ext=m4a]/bv*[height<=480][ext=mp4]+ba[ext=m4a]"
            "/bv*[height<=480]+ba/b[height<=480]",
            "--merge-output-format",
            "mp4",
            "--embed-chapters",
            "--embed-metadata",
            "--no-playlist",
            "--concurrent-fragments",
            "1",
            "--retries",
            "5",
            "--fragment-retries",
            "5",
            "--external-downloader",
            "aria2c",
            "--external-downloader-args",
            "aria2c:-x 4 -s 4 -j 4 --file-allocation=none --retry-wait=1",
            "--abort-on-unavailable-fragment",
            "--keep-fragments",
            "--no-check-certificates",
            "--remux-video",
            "mp4",
        ],
    ),
    "e_http_aria2c_unavailable": dict(
        url=PLAIN_HTTP,
        options=DownloadOptions(quality="480p", container="mp4", use_aria2c=True),
        stream_type="http",
        aria2c_available=False,
        js_runtime="deno",
        cookies_path=None,
        script=[
            "--format",
            "bv*[height<=480][vcodec^=avc1]+ba[ext=m4a]/bv*[height<=480][ext=mp4]+ba[ext=m4a]"
            "/bv*[height<=480]+ba/b[height<=480]",
            "--merge-output-format",
            "mp4",
            "--embed-chapters",
            "--embed-metadata",
            "--no-playlist",
            "--concurrent-fragments",
            "1",
            "--retries",
            "5",
            "--fragment-retries",
            "5",
            "--abort-on-unavailable-fragment",
            "--keep-fragments",
            "--no-check-certificates",
            "--remux-video",
            "mp4",
        ],
    ),
    "f_best": dict(
        url=VIMEO,
        options=DownloadOptions(quality="best"),
        stream_type="hls",
        aria2c_available=True,
        js_runtime="deno",
        cookies_path=None,
        script=[
            "--format",
            "bv*+ba/b",
            "--merge-output-format",
            "mkv",
            "--embed-chapters",
            "--embed-metadata",
            "--no-playlist",
            "--concurrent-fragments",
            "4",
            "--retries",
            "5",
            "--fragment-retries",
            "5",
            "--http-chunk-size",
            "10M",
            "--buffer-size",
            "16K",
            "--abort-on-unavailable-fragment",
            "--keep-fragments",
            "--no-check-certificates",
            "--remux-video",
            "mkv",
        ],
    ),
    "g_cookies": dict(
        url=YOUTUBE,
        options=DownloadOptions(quality="1080p"),
        stream_type="dash",
        aria2c_available=True,
        js_runtime="deno",
        cookies_path=Path("/config/cookies/youtube.txt"),
        script=[
            "--format",
            "bv*[height<=1080]+ba/b[height<=1080]",
            "--merge-output-format",
            "mkv",
            "--embed-chapters",
            "--embed-metadata",
            "--no-playlist",
            "--concurrent-fragments",
            "4",
            "--retries",
            "5",
            "--fragment-retries",
            "5",
            "--http-chunk-size",
            "10M",
            "--buffer-size",
            "16K",
            "--cookies",
            "/config/cookies/youtube.txt",
            "--abort-on-unavailable-fragment",
            "--keep-fragments",
            "--no-check-certificates",
            "--remote-components",
            "ejs:github",
            "--remux-video",
            "mkv",
        ],
    ),
}


@pytest.mark.parametrize("case", list(CASES.values()), ids=list(CASES))
def test_argv_matches_script(case: dict) -> None:
    stream_type: StreamType = case["stream_type"]
    resolved = resolve_auto(stream_type, case["options"], case["aria2c_available"])

    argv = build_argv(
        case["url"],
        case["options"],
        resolved,
        job_dir=JOB_DIR,
        cookies_path=case["cookies_path"],
        js_runtime=case["js_runtime"],
    )

    assert argv == [*case["script"], *FETCHARR_ADDITIONS, case["url"]]


def test_fetcharr_additions_block() -> None:
    options = DownloadOptions(quality="720p")
    argv = build_argv(
        PLAIN_HTTP,
        options,
        resolve_auto("http", options, aria2c_available=False),
        job_dir=JOB_DIR,
        js_runtime=None,
    )

    start = argv.index("--newline")
    assert argv[start:-1] == FETCHARR_ADDITIONS
    assert argv[-1] == PLAIN_HTTP
