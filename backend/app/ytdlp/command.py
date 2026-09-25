"""Port of the `CMD` assembly in download_video.sh, plus fetcharr's additions (§4)."""

from pathlib import Path
from urllib.parse import urlsplit

from app.transcode.profiles import TranscodeProfile
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
        build_selector(
            options.quality,
            container,
            # Keep the decode on the GPU when the file is going to be re-encoded (§4.1).
            prefer_gpu_decode=options.transcode is not TranscodeProfile.OFF,
            video_codec=options.video_codec,
            audio_language=options.audio_language,
            allow_hdr=options.allow_hdr,
        ),
        "--merge-output-format",
        container,
    ]
    if options.embed_chapters:
        argv.append("--embed-chapters")
    if options.embed_metadata:
        argv.append("--embed-metadata")
    argv += [
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

    argv += _subtitle_args(options)
    argv += _sponsorblock_args(options)
    if options.rate_limit is not None:
        argv += ["--limit-rate", options.rate_limit]

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


def _subtitle_args(options: DownloadOptions) -> list[str]:
    """`embed` keeps them in the container, `sidecar` writes `<id>.<lang>.srt` (§5 step 2d)."""
    subtitles = options.subtitles
    if subtitles.mode == "off":
        return []
    argv = ["--write-subs", "--sub-langs", ",".join(subtitles.languages)]
    if subtitles.include_auto_captions:
        argv.append("--write-auto-subs")
    if subtitles.mode == "embed":
        argv.append("--embed-subs")
    else:
        # The Organizer renames the converted file to `<video base>.<lang>.srt` (§7.2).
        argv += ["--convert-subs", "srt"]
    return argv


def _sponsorblock_args(options: DownloadOptions) -> list[str]:
    sponsorblock = options.sponsorblock
    if sponsorblock.mode == "off":
        return []
    flag = "--sponsorblock-mark" if sponsorblock.mode == "mark" else "--sponsorblock-remove"
    return [flag, ",".join(sponsorblock.chosen())]


def downgrade_fragments(argv: list[str]) -> list[str]:
    """The script's exit-code-2 fallback: the same argv with `--concurrent-fragments 1`."""
    downgraded = list(argv)
    downgraded[downgraded.index("--concurrent-fragments") + 1] = "1"
    return downgraded
