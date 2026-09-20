"""Port of the `CMD` assembly in download_video.sh, plus fetcharr's additions (§4)."""

from pathlib import Path
from urllib.parse import urlsplit

from app.ytdlp.formats import build_selector
from app.ytdlp.runtime import JsRuntime
from app.ytdlp.schemas import DownloadOptions
from app.ytdlp.stream import Resolved

ARIA2C_ARGS = "aria2c:-x 4 -s 4 -j 4 --file-allocation=none --retry-wait=1"


def is_youtube_url(url: str) -> bool:
    host = urlsplit(url).hostname or ""
    return host in ("youtube.com", "youtu.be") or host.endswith(".youtube.com")


def build_argv(
    url: str,
    options: DownloadOptions,
    resolved: Resolved,
    *,
    job_dir: Path,
    cookies_path: Path | None = None,
    js_runtime: JsRuntime | None,
) -> list[str]:
    """The yt-dlp arguments (without the binary) for one download, URL last."""
    if url.startswith("-"):
        raise ValueError("URL must not start with '-'")

    container = options.container
    argv = [
        "--format",
        build_selector(options.quality, container),
        "--merge-output-format",
        container,
        "--embed-chapters",
        "--embed-metadata",
        "--no-playlist",
        "--concurrent-fragments",
        str(resolved.fragments),
        "--retries",
        str(options.retries),
        "--fragment-retries",
        str(options.retries),
    ]

    if resolved.stream_type in ("hls", "dash"):
        argv += ["--http-chunk-size", "10M", "--buffer-size", "16K"]

    if resolved.use_aria2c:
        argv += ["--external-downloader", "aria2c", "--external-downloader-args", ARIA2C_ARGS]

    if cookies_path is not None:
        argv += ["--cookies", str(cookies_path)]

    argv += ["--abort-on-unavailable-fragment", "--keep-fragments", "--no-check-certificates"]

    # YouTube JS challenge (n-sig) solver. yt-dlp enables deno by default; node needs the flag.
    if is_youtube_url(url):
        argv += ["--remote-components", "ejs:github"]
        if js_runtime == "node":
            argv += ["--js-runtimes", "node"]

    # Transcoding is a separate ffmpeg step (M7), so the download always remuxes.
    argv += ["--remux-video", container]

    argv += [
        "--newline",
        "--progress",
        "--progress-template",
        "download:FA_PROGRESS %(progress)j",
        "--print-to-file",
        "after_move:%(filepath)s",
        str(job_dir / "final_path"),
        "-P",
        f"home:{job_dir}",
        "-P",
        f"temp:{job_dir / 'tmp'}",
        "-o",
        "%(id)s.%(ext)s",
    ]

    argv.append(url)
    return argv


def downgrade_fragments(argv: list[str]) -> list[str]:
    """The script's exit-code-2 fallback: the same argv with `--concurrent-fragments 1`."""
    downgraded = list(argv)
    downgraded[downgraded.index("--concurrent-fragments") + 1] = "1"
    return downgraded
