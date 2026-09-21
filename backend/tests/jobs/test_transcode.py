"""The transcode step end to end: the real encode, the fallback, recovery and cancel (§6.1)."""

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.config import Settings
from app.db.session import Database
from app.events.service import EventHub
from app.jobs.constants import JobStatus, Step
from app.jobs.manager import JobManager
from app.ytdlp.schemas import DownloadOptions
from tests.conftest import exists, is_file, names, wait_until
from tests.fake_ffmpeg import FakeFfmpeg
from tests.fake_ytdlp import FakeYtdlp
from tests.jobs.conftest import TERMINAL, wait_for_status
from tests.transcode.conftest import copy_media, video_codec, write


def _options(profile: str, **extra: Any) -> DownloadOptions:
    return DownloadOptions(quality="best", retries=0, transcode=profile, **extra)


def _encoder(argv: list[str]) -> str:
    return argv[argv.index("-c:v") + 1]


# ------------------------------------------------- AC4: software transcode end to end


async def test_software_transcode_end_to_end_mkv(
    manager: JobManager,
    new_job: Callable[..., Any],
    read_job: Callable[[str], Any],
    fake_ytdlp: FakeYtdlp,
    media: dict[str, Path],
) -> None:
    """Real ffmpeg: the finished file in completed/ is HEVC, and the job dir is gone."""
    fake_ytdlp.downloads(media["served"])
    job_id = await new_job(options=_options("x265-software"))
    manager.wake()

    job = await wait_for_status(read_job, job_id, *TERMINAL)

    assert job.status == JobStatus.COMPLETED, job.error_message
    assert job.transcode_fallback_used is False
    completed = Path(job.completed_path)
    assert completed.suffix == ".mkv"
    assert (await asyncio.to_thread(video_codec, completed))[0] == "hevc"


async def test_software_transcode_end_to_end_mp4(
    manager: JobManager,
    new_job: Callable[..., Any],
    read_job: Callable[[str], Any],
    fake_ytdlp: FakeYtdlp,
    media: dict[str, Path],
) -> None:
    """The script's mp4 extras applied for real: HEVC tagged `hvc1` (§4.1)."""
    fake_ytdlp.downloads(media["served"])
    job_id = await new_job(options=_options("x265-software", container="mp4"))
    manager.wake()

    job = await wait_for_status(read_job, job_id, *TERMINAL)

    assert job.status == JobStatus.COMPLETED, job.error_message
    completed = Path(job.completed_path)
    assert completed.suffix == ".mp4"
    assert await asyncio.to_thread(video_codec, completed) == ("hevc", "hvc1")


# ---------------------------------------- AC15: nothing transcodes unless it was asked


async def test_a_download_with_default_options_never_transcodes(
    manager: JobManager,
    settings: Settings,
    new_job: Callable[..., Any],
    read_job: Callable[[str], Any],
    fake_ytdlp: FakeYtdlp,
    fake_ffmpeg: FakeFfmpeg,
    media: dict[str, Path],
) -> None:
    """Transcoding is opt-in: an untouched download starts no ffmpeg at all (§5 step 2d)."""
    fake_ytdlp.downloads(media["small"])
    job_id = await new_job()
    manager.wake()

    job = await wait_for_status(read_job, job_id, *TERMINAL)

    assert job.status == JobStatus.COMPLETED, job.error_message
    assert fake_ffmpeg.calls == []
    assert job.transcode_fallback_used is False
    assert job.step_timings.get(Step.TRANSCODE) is not None  # the step ran, and did nothing
    assert not exists(settings.incomplete_dir / job_id)


# ------------------------------------------------------------- AC5: the fallback


async def test_hardware_failure_falls_back_to_software_once(
    manager: JobManager,
    new_job: Callable[..., Any],
    read_job: Callable[[str], Any],
    read_logs: Callable[[str], Any],
    fake_ytdlp: FakeYtdlp,
    fake_ffmpeg: FakeFfmpeg,
    media: dict[str, Path],
) -> None:
    fake_ytdlp.downloads(media["small"])
    fake_ffmpeg.fails_for("hevc_qsv", media["served"])
    job_id = await new_job(options=_options("hevc-qsv"))
    manager.wake()

    job = await wait_for_status(read_job, job_id, *TERMINAL)

    assert job.status == JobStatus.COMPLETED, job.error_message
    assert job.transcode_fallback_used is True
    assert [_encoder(call) for call in fake_ffmpeg.calls] == ["hevc_qsv", "libx265"]
    logs = await read_logs(job_id)
    assert any("falling back to x265-software" in line for line in logs)


async def test_a_second_failure_fails_the_job_without_downloading_again(
    manager: JobManager,
    new_job: Callable[..., Any],
    read_job: Callable[[str], Any],
    fake_ytdlp: FakeYtdlp,
    fake_ffmpeg: FakeFfmpeg,
    media: dict[str, Path],
) -> None:
    """The fallback is tried once; the download is never repeated to get there (§6.1)."""
    fake_ytdlp.downloads(media["small"])
    fake_ffmpeg.always_fails()
    job_id = await new_job(options=_options("hevc-vaapi"))
    manager.wake()

    job = await wait_for_status(read_job, job_id, *TERMINAL)

    assert job.status == JobStatus.FAILED
    assert job.error_code == "TranscodeFailed"
    assert [_encoder(call) for call in fake_ffmpeg.calls] == ["hevc_vaapi", "libx265"]
    assert len(fake_ytdlp.calls) == 1


# --------------------------------------------------------------- AC6: retry


async def test_retry_after_a_failed_transcode_does_not_download_again(
    manager: JobManager,
    settings: Settings,
    new_job: Callable[..., Any],
    read_job: Callable[[str], Any],
    fake_ytdlp: FakeYtdlp,
    fake_ffmpeg: FakeFfmpeg,
    media: dict[str, Path],
    hub: EventHub,
    db: Database,
) -> None:
    from app.jobs.service import JobService

    job_id = await new_job(
        options=_options("x265-software"),
        status=JobStatus.FAILED,
        last_completed_step=Step.DOWNLOAD,
        error_code="TranscodeFailed",
        error_message="encoder unavailable",
    )
    job_dir = settings.incomplete_dir / job_id
    video = await asyncio.to_thread(copy_media, media["small"], job_dir / "video.mkv")
    await asyncio.to_thread(write, job_dir / "final_path", f"{video}\n")
    fake_ytdlp.downloads(media["small"])
    fake_ffmpeg.transcodes(media["served"])

    await JobService(db, settings, hub, manager).retry(job_id)
    job = await wait_for_status(read_job, job_id, *TERMINAL)

    assert job.status == JobStatus.COMPLETED, job.error_message
    assert fake_ytdlp.calls == []
    assert len(fake_ffmpeg.calls) == 1
    assert is_file(Path(job.completed_path))


# ------------------------------------------------------------ AC7: recovery


async def test_resume_mid_transcode_clears_the_stale_temp_file(
    make_manager: Callable[..., JobManager],
    settings: Settings,
    new_job: Callable[..., Any],
    read_job: Callable[[str], Any],
    fake_ytdlp: FakeYtdlp,
    fake_ffmpeg: FakeFfmpeg,
    media: dict[str, Path],
) -> None:
    """A crash mid-encode: the half-written file goes, the source stands, the step redoes."""
    job_id = await new_job(
        options=_options("x265-software"),
        status=JobStatus.TRANSCODING,
        last_completed_step=Step.DOWNLOAD,
    )
    job_dir = settings.incomplete_dir / job_id
    video = await asyncio.to_thread(copy_media, media["small"], job_dir / "video.mkv")
    await asyncio.to_thread(write, job_dir / "final_path", f"{video}\n")
    stale = await asyncio.to_thread(write, job_dir / "transcoded.tmp.mkv", "half written")
    fake_ytdlp.downloads(media["small"])
    fake_ffmpeg.transcodes(media["served"])

    manager = make_manager()
    await manager.start()
    try:
        job = await wait_for_status(read_job, job_id, *TERMINAL)
    finally:
        await manager.stop()

    assert job.status == JobStatus.COMPLETED, job.error_message
    assert not exists(stale)
    assert fake_ytdlp.calls == []
    assert len(fake_ffmpeg.calls) == 1
    # The transcode's own output is what landed in completed/, not the stale temp file.
    assert is_file(Path(job.completed_path))
    assert names(settings.completed_dir / "other") == [Path(job.completed_path).name]


# -------------------------------------------------------- AC8: the transcode slot


async def test_one_transcode_at_a_time_while_another_job_downloads(
    manager: JobManager,
    new_job: Callable[..., Any],
    read_job: Callable[[str], Any],
    fake_ytdlp: FakeYtdlp,
    fake_ffmpeg: FakeFfmpeg,
    media: dict[str, Path],
    tmp_path: Path,
) -> None:
    """MAX_CONCURRENT_TRANSCODES is 1, and holding that slot blocks no download (§6.1)."""
    gate = tmp_path / "gate"
    fake_ytdlp.downloads(media["small"])
    fake_ffmpeg.transcodes(media["served"], gate=gate)
    transcoding = [
        await new_job(video_id=f"t{index}", options=_options("x265-software")) for index in range(2)
    ]
    plain = await new_job(video_id="plain")
    manager.wake()

    # One transcode is gated; the plain download is free to finish behind it.
    await wait_until(lambda: len(fake_ffmpeg.calls) == 1)
    job = await wait_for_status(read_job, plain, *TERMINAL)
    assert job.status == JobStatus.COMPLETED, job.error_message
    await asyncio.sleep(0.2)
    assert len(fake_ffmpeg.calls) == 1

    await asyncio.to_thread(write, gate, "go")
    for job_id in transcoding:
        finished = await wait_for_status(read_job, job_id, *TERMINAL)
        assert finished.status == JobStatus.COMPLETED, finished.error_message
    assert fake_ffmpeg.max_concurrent == 1


# ------------------------------------------------------------- AC9: cancel


async def test_cancel_during_transcode_kills_the_process_group(
    manager: JobManager,
    settings: Settings,
    new_job: Callable[..., Any],
    read_job: Callable[[str], Any],
    fake_ytdlp: FakeYtdlp,
    fake_ffmpeg: FakeFfmpeg,
    media: dict[str, Path],
) -> None:
    fake_ytdlp.downloads(media["small"])
    fake_ffmpeg.hangs()
    job_id = await new_job(options=_options("hevc-qsv"))
    manager.wake()

    await wait_until(fake_ffmpeg.pids_file.exists)
    pids = fake_ffmpeg.pids()
    assert manager.request_cancel(job_id) is True
    job = await wait_for_status(read_job, job_id, *TERMINAL)

    assert job.status == JobStatus.CANCELLED
    assert not exists(settings.incomplete_dir / job_id)
    for pid in pids:
        await wait_until(lambda pid=pid: _gone(pid), seconds=5)


def _gone(pid: int) -> bool:
    import os

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return False
