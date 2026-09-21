"""The ffmpeg transcode runner: the progress parser, the in-place replace and the fallback."""

import asyncio
from pathlib import Path

import pytest

from app.transcode.profiles import TranscodeProfile
from app.transcode.runner import (
    TranscodeCancelled,
    TranscodeFailed,
    clear_temp_files,
    percent,
    transcode,
)
from tests.conftest import exists, is_file, wait_until
from tests.fake_ffmpeg import FakeFfmpeg
from tests.transcode.conftest import copy_media, listing, read_bytes, video_codec, write

#: One `-progress pipe:1` block, captured verbatim from ffmpeg 8.0.
PROGRESS_BLOCK = """frame=20
fps=0.00
stream_0_0_q=27.3
bitrate= 178.7kbits/s
total_size=40197
out_time_us=900000
out_time_ms=900000
out_time=00:00:00.900000
dup_frames=0
drop_frames=0
speed=  25x
progress=continue"""

DURATION = 1.8


# ----------------------------------------------------------------- AC3: the parser


def test_percent_from_out_time_us() -> None:
    reported = [percent(line, DURATION) for line in PROGRESS_BLOCK.splitlines()]

    # Exactly one line in the block carries a timestamp, and it is half way through.
    assert [value for value in reported if value is not None] == [50.0]


def test_progress_end_reports_100() -> None:
    assert percent("progress=end", DURATION) == 100.0
    assert percent("progress=continue", DURATION) is None


def test_unparsable_and_unknown_keys_are_ignored() -> None:
    assert percent("out_time_us=N/A", DURATION) is None
    assert percent("bitrate= 178.7kbits/s", DURATION) is None
    assert percent("frame=20", DURATION) is None
    assert percent("[hevc_qsv @ 0x1] Error initializing", DURATION) is None
    assert percent("out_time_us=900000", None) is None
    assert percent("out_time_us=900000", 0) is None


def test_percent_never_exceeds_100() -> None:
    assert percent("out_time_us=9000000", DURATION) == 100.0


# ------------------------------------------------- the temp file and the done marker


def test_clear_temp_files_only_removes_the_transcode_leftovers(tmp_path: Path) -> None:
    write(tmp_path / "transcoded.tmp.mkv")
    write(tmp_path / "transcoded.tmp.mp4")
    write(tmp_path / "video.mkv", "keep me")

    clear_temp_files(tmp_path)

    assert listing(tmp_path) == ["video.mkv"]


async def test_success_replaces_the_source_and_writes_the_marker(
    tmp_path: Path, media: dict[str, Path]
) -> None:
    """Real ffmpeg: the source is replaced in place and the done-check marker goes down."""
    job_dir = tmp_path / "job"
    source = await asyncio.to_thread(copy_media, media["served"], job_dir / "clip.mkv")
    before = await asyncio.to_thread(read_bytes, source)
    percents: list[float] = []

    fell_back = await transcode(
        profile=TranscodeProfile.X265_SOFTWARE,
        source=source,
        job_dir=job_dir,
        container="mkv",
        quality={"x265-software": 30},
        duration=2.0,
        cancel=asyncio.Event(),
        on_percent=percents.append,
        on_log=lambda _line: None,
        driver="iHD",
    )

    assert fell_back is False
    assert is_file(job_dir / "transcode.done")
    assert listing(job_dir) == ["clip.mkv", "transcode.done"]
    assert await asyncio.to_thread(read_bytes, source) != before
    # Matroska carries no codec tag, so only the codec is meaningful here; `hvc1` is
    # asserted on the mp4 path, where the script's tag actually applies.
    assert (await asyncio.to_thread(video_codec, source))[0] == "hevc"
    assert percents and percents[-1] == 100.0


# ------------------------------------------------------------- AC5: the fallback


async def test_a_hardware_failure_falls_back_to_x265_once(
    tmp_path: Path, media: dict[str, Path], fake_ffmpeg: FakeFfmpeg
) -> None:
    job_dir = tmp_path / "job"
    source = await asyncio.to_thread(copy_media, media["small"], job_dir / "clip.mkv")
    fake_ffmpeg.fails_for("hevc_qsv", media["served"])
    logged: list[str] = []

    fell_back = await transcode(
        profile=TranscodeProfile.HEVC_QSV,
        source=source,
        job_dir=job_dir,
        container="mkv",
        quality=None,
        duration=1.0,
        cancel=asyncio.Event(),
        on_percent=lambda _pct: None,
        on_log=logged.append,
        driver="iHD",
    )

    assert fell_back is True
    assert [_encoder(call) for call in fake_ffmpeg.calls] == ["hevc_qsv", "libx265"]
    assert any("falling back to x265-software" in line for line in logged)
    assert is_file(job_dir / "transcode.done")
    assert not exists(job_dir / "transcoded.tmp.mkv")


async def test_a_software_failure_is_not_retried(
    tmp_path: Path, media: dict[str, Path], fake_ffmpeg: FakeFfmpeg
) -> None:
    job_dir = tmp_path / "job"
    source = await asyncio.to_thread(copy_media, media["small"], job_dir / "clip.mkv")
    fake_ffmpeg.always_fails()

    with pytest.raises(TranscodeFailed):
        await transcode(
            profile=TranscodeProfile.X265_SOFTWARE,
            source=source,
            job_dir=job_dir,
            container="mkv",
            quality=None,
            duration=1.0,
            cancel=asyncio.Event(),
            on_percent=lambda _pct: None,
            on_log=lambda _line: None,
            driver="iHD",
        )

    assert len(fake_ffmpeg.calls) == 1
    assert not exists(job_dir / "transcode.done")


async def test_a_stale_temp_file_is_cleared_before_the_run(
    tmp_path: Path, media: dict[str, Path], fake_ffmpeg: FakeFfmpeg
) -> None:
    """§6.1: after a crash the filesystem wins, so the half-written file goes first."""
    job_dir = tmp_path / "job"
    source = await asyncio.to_thread(copy_media, media["small"], job_dir / "clip.mkv")
    stale = await asyncio.to_thread(write, job_dir / "transcoded.tmp.mkv", "half written")
    fake_ffmpeg.transcodes(media["served"])

    await transcode(
        profile=TranscodeProfile.X265_SOFTWARE,
        source=source,
        job_dir=job_dir,
        container="mkv",
        quality=None,
        duration=1.0,
        cancel=asyncio.Event(),
        on_percent=lambda _pct: None,
        on_log=lambda _line: None,
        driver="iHD",
    )

    assert not exists(stale)
    assert await asyncio.to_thread(read_bytes, source) != b"half written"


async def test_the_configured_driver_reaches_ffmpeg(
    tmp_path: Path, media: dict[str, Path], fake_ffmpeg: FakeFfmpeg
) -> None:
    job_dir = tmp_path / "job"
    source = await asyncio.to_thread(copy_media, media["small"], job_dir / "clip.mkv")
    fake_ffmpeg.transcodes(media["served"])

    await transcode(
        profile=TranscodeProfile.X265_SOFTWARE,
        source=source,
        job_dir=job_dir,
        container="mkv",
        quality=None,
        duration=1.0,
        cancel=asyncio.Event(),
        on_percent=lambda _pct: None,
        on_log=lambda _line: None,
        driver="radeonsi",
    )

    assert fake_ffmpeg.drivers == ["radeonsi"]


# -------------------------------------------------------------- AC9: cancellation


async def test_cancel_kills_the_process_group(
    tmp_path: Path, media: dict[str, Path], fake_ffmpeg: FakeFfmpeg
) -> None:
    job_dir = tmp_path / "job"
    source = await asyncio.to_thread(copy_media, media["small"], job_dir / "clip.mkv")
    fake_ffmpeg.hangs()
    cancel = asyncio.Event()

    running = asyncio.create_task(
        transcode(
            profile=TranscodeProfile.X265_SOFTWARE,
            source=source,
            job_dir=job_dir,
            container="mkv",
            quality=None,
            duration=1.0,
            cancel=cancel,
            on_percent=lambda _pct: None,
            on_log=lambda _line: None,
            driver="iHD",
        )
    )
    await wait_until(fake_ffmpeg.pids_file.exists)
    pids = fake_ffmpeg.pids()
    cancel.set()

    with pytest.raises(TranscodeCancelled):
        await running
    for pid in pids:
        await wait_until(lambda pid=pid: _gone(pid), seconds=5)


def _gone(pid: int) -> bool:
    import os

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return False


def _encoder(argv: list[str]) -> str:
    return argv[argv.index("-c:v") + 1]
