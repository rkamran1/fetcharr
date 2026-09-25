"""The durable pipeline end to end: progress, throttling, cancel, concurrency, recovery."""

import asyncio
import time
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import event

from app.config import Settings
from app.db.base import utcnow
from app.db.session import Database
from app.events.service import EventHub
from app.jobs.constants import JobStatus, Step
from app.jobs.manager import PROGRESS_DB_INTERVAL_S, JobManager
from app.library.naming import DailyEpisode, Episode
from app.library.organizer import MARKER
from app.ytdlp.schemas import DownloadOptions, SubtitleOptions
from tests.conftest import exists, is_file, names, setup_account, wait_until
from tests.fake_ytdlp import FakeYtdlp
from tests.jobs.conftest import TERMINAL, wait_for_status

# --------------------------------------------------------------- AC1: end to end


async def test_other_download_completes_end_to_end(
    app: Any, client: httpx.AsyncClient, settings: Settings, media_server: str
) -> None:
    """Real yt-dlp against a local http.server: request → completed file, no internet."""
    await setup_account(client)

    inspected = await client.post("/api/inspect", json={"url": media_server})
    assert inspected.status_code == 200, inspected.text
    inspection = inspected.json()

    created = await client.post(
        "/api/requests",
        json={
            "media_type": "other",
            "items": [{"inspection_id": inspection["inspection_id"]}],
            "options": {"quality": "best", "container": "mkv"},
        },
    )
    assert created.status_code == 201, created.text
    job_id = created.json()["jobs"][0]

    async def finished() -> bool:
        response = await client.get(f"/api/jobs/{job_id}")
        return response.json()["status"] in TERMINAL

    async with asyncio.timeout(60):
        while True:
            if await finished():
                break
            await asyncio.sleep(0.1)

    job = (await client.get(f"/api/jobs/{job_id}")).json()
    assert job["status"] == JobStatus.COMPLETED, job["error_message"]
    assert job["import_status"] == "n/a"
    assert job["file_size"] and job["file_size"] > 0
    # A finished job reads as finished, not as one still moving (AC19).
    assert job["progress_pct"] == 100
    assert job["speed_bps"] is None
    assert job["eta_s"] is None
    assert job["phase"] is None
    assert job["finished_at"]
    completed = Path(job["completed_path"])
    assert completed == settings.completed_dir / "other" / f"video [{inspection['id']}].mkv"
    assert is_file(completed)
    assert not exists(settings.incomplete_dir / job_id)


# ------------------------------------------------- AC3/AC4: how the writes behave


async def test_progress_is_written_to_the_db_at_most_every_two_seconds(
    manager: JobManager,
    db: Database,
    new_job: Callable[..., Any],
    read_job: Callable[[str], Any],
    fake_ytdlp: FakeYtdlp,
    media: dict[str, Path],
) -> None:
    fake_ytdlp.downloads(media["small"], progress_lines=50, delay=0.05)
    updates: list[str] = []

    @event.listens_for(db.writer.sync_engine, "before_cursor_execute")
    def _count(conn, cursor, statement, parameters, context, executemany) -> None:  # noqa: ANN001
        if statement.lstrip().upper().startswith("UPDATE JOBS") and "downloaded_bytes" in statement:
            updates.append(statement)

    started = time.monotonic()
    job_id = await new_job()
    manager.wake()
    job = await wait_for_status(read_job, job_id, *TERMINAL)
    elapsed = time.monotonic() - started

    assert job.status == JobStatus.COMPLETED, job.error_message
    # 50 progress lines: one write when the first arrives, then at most one per
    # PROGRESS_DB_INTERVAL_S, however long the run takes on this machine.
    assert 1 <= len(updates) <= elapsed / PROGRESS_DB_INTERVAL_S + 1, (elapsed, updates)


async def test_no_write_transaction_is_held_across_the_subprocess(
    manager: JobManager,
    db: Database,
    new_job: Callable[..., Any],
    read_job: Callable[[str], Any],
    fake_ytdlp: FakeYtdlp,
    media: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§3.1 rule 2: a write session never spans the yt-dlp run."""
    sessions: list[list[float]] = []
    subprocess_window: list[float] = []

    original_write = Database.write_session
    original_exec = asyncio.create_subprocess_exec

    def spy_write(self: Database):  # noqa: ANN202 - an async context manager
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def wrapper():  # noqa: ANN202
            record = [time.monotonic(), 0.0]
            sessions.append(record)
            async with original_write(self) as session:
                yield session
            record[1] = time.monotonic()

        return wrapper()

    async def spy_exec(*args: Any, **kwargs: Any):  # noqa: ANN202
        subprocess_window.append(time.monotonic())
        process = await original_exec(*args, **kwargs)
        return process

    monkeypatch.setattr(Database, "write_session", spy_write)
    monkeypatch.setattr("app.ytdlp.runner.asyncio.create_subprocess_exec", spy_exec)

    fake_ytdlp.downloads(media["small"], progress_lines=5, delay=0.05)
    job_id = await new_job()
    manager.wake()
    job = await wait_for_status(read_job, job_id, *TERMINAL)
    assert job.status == JobStatus.COMPLETED, job.error_message

    started = subprocess_window[0]
    ended = time.monotonic()
    open_at_start = [s for s in sessions if s[0] <= started <= (s[1] or ended)]
    assert open_at_start == [], "a write transaction was open when yt-dlp started"
    overlapping = [s for s in sessions if s[1] >= started]
    assert overlapping, "expected progress writes during the download"
    assert max(end - begin for begin, end in overlapping) < 0.1


# ------------------------------------------------------- AC5/AC6: failure handling


async def test_attempts_are_recorded_in_job_logs(
    manager: JobManager,
    new_job: Callable[..., Any],
    read_job: Callable[[str], Any],
    fake_ytdlp: FakeYtdlp,
    read_logs: Callable[[str], Any],
) -> None:
    from app.ytdlp.schemas import DownloadOptions

    fake_ytdlp.downloads(exit_code=1, stderr="ERROR: unable to download video data")
    job_id = await new_job(options=DownloadOptions(quality="best", retries=2))
    manager.wake()
    job = await wait_for_status(read_job, job_id, *TERMINAL)

    assert job.status == JobStatus.FAILED
    assert job.attempt == 3
    lines = await read_logs(job_id)
    assert [line for line in lines if line.startswith("yt-dlp attempt")] == [
        "yt-dlp attempt 1",
        "yt-dlp attempt 2",
        "yt-dlp attempt 3",
    ]


async def test_failed_job_reports_the_error_and_leaves_completed_untouched(
    manager: JobManager,
    settings: Settings,
    new_job: Callable[..., Any],
    read_job: Callable[[str], Any],
    fake_ytdlp: FakeYtdlp,
) -> None:
    fake_ytdlp.downloads(exit_code=1, stderr="ERROR: unable to download video data")
    job_id = await new_job()
    manager.wake()
    job = await wait_for_status(read_job, job_id, *TERMINAL)

    assert job.status == JobStatus.FAILED
    assert job.error_code and job.error_message
    assert names(settings.completed_dir / "other") == []


# ------------------------------------------------------------------- AC7: cancel


async def test_cancel_during_download_cancels_the_job(
    manager: JobManager,
    settings: Settings,
    new_job: Callable[..., Any],
    read_job: Callable[[str], Any],
    fake_ytdlp: FakeYtdlp,
) -> None:
    fake_ytdlp.downloads(progress_lines=1, spawn_child=True)
    job_id = await new_job()
    manager.wake()

    await wait_until(fake_ytdlp.pids_file.exists)
    pids = fake_ytdlp.pids()
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


# -------------------------------------------------------------- AC8: concurrency


async def test_at_most_two_jobs_download_at_once(
    manager: JobManager,
    new_job: Callable[..., Any],
    read_job: Callable[[str], Any],
    fake_ytdlp: FakeYtdlp,
    media: dict[str, Path],
    tmp_path: Path,
) -> None:
    gate = tmp_path / "gate"
    fake_ytdlp.downloads(media["small"], progress_lines=1, gate=gate)
    job_ids = [await new_job(video_id=f"v{index}") for index in range(3)]
    manager.wake()

    # Two stubs reach the gate; the third can't start until a slot frees up.
    await wait_until(lambda: len(fake_ytdlp.calls) == 2)
    await asyncio.sleep(0.2)
    assert len(fake_ytdlp.calls) == 2
    gate.write_text("go")

    for job_id in job_ids:
        job = await wait_for_status(read_job, job_id, *TERMINAL)
        assert job.status == JobStatus.COMPLETED, job.error_message
    assert fake_ytdlp.max_concurrent == 2


# ---------------------------------------------------------------- AC9: recovery


async def test_resume_mid_download(
    make_manager: Callable[..., JobManager],
    new_job: Callable[..., Any],
    read_job: Callable[[str], Any],
    fake_ytdlp: FakeYtdlp,
    media: dict[str, Path],
    tmp_path: Path,
) -> None:
    gate = tmp_path / "gate"
    fake_ytdlp.downloads(media["small"], progress_lines=1, gate=gate)
    job_id = await new_job()

    crashed = make_manager()
    await crashed.start()
    await wait_until(lambda: len(fake_ytdlp.calls) == 1)
    await crashed.stop()  # the container dies mid-download

    gate.write_text("go")
    fake_ytdlp.downloads(media["small"], progress_lines=1)
    restarted = make_manager()
    await restarted.start()
    try:
        job = await wait_for_status(read_job, job_id, *TERMINAL)
    finally:
        await restarted.stop()

    assert job.status == JobStatus.COMPLETED, job.error_message


async def test_resume_after_download_does_not_download_again(
    make_manager: Callable[..., JobManager],
    settings: Settings,
    new_job: Callable[..., Any],
    read_job: Callable[[str], Any],
    fake_ytdlp: FakeYtdlp,
    media: dict[str, Path],
) -> None:
    """The done-check sees a playable file, so yt-dlp is never run again (§6.1)."""
    job_id = await new_job(status=JobStatus.DOWNLOADING, last_completed_step=Step.DOWNLOAD)
    job_dir = settings.incomplete_dir / job_id
    job_dir.mkdir(parents=True)
    video = job_dir / "video.mkv"
    video.write_bytes(media["small"].read_bytes())
    (job_dir / "final_path").write_text(f"{video}\n")
    fake_ytdlp.downloads(media["small"])

    manager = make_manager()
    await manager.start()
    try:
        job = await wait_for_status(read_job, job_id, *TERMINAL)
    finally:
        await manager.stop()

    assert job.status == JobStatus.COMPLETED, job.error_message
    assert fake_ytdlp.calls == []
    assert is_file(Path(job.completed_path))


async def test_resume_between_sidecar_and_video_moves(
    make_manager: Callable[..., JobManager],
    settings: Settings,
    new_job: Callable[..., Any],
    read_job: Callable[[str], Any],
    media: dict[str, Path],
) -> None:
    """A crash after the marker was written: organize finishes with exactly one file."""
    job_id = await new_job(status=JobStatus.ORGANIZING, last_completed_step=Step.TRANSCODE)
    job_dir = settings.incomplete_dir / job_id
    job_dir.mkdir(parents=True)
    video = job_dir / "video.mkv"
    video.write_bytes(media["small"].read_bytes())
    (job_dir / "final_path").write_text(f"{video}\n")
    destination = settings.completed_dir / "other" / "Big Buck Bunny [abc123].mkv"
    destination.parent.mkdir(parents=True, exist_ok=True)
    (job_dir / MARKER).write_text(str(destination))

    manager = make_manager()
    await manager.start()
    try:
        job = await wait_for_status(read_job, job_id, *TERMINAL)
    finally:
        await manager.stop()

    assert job.status == JobStatus.COMPLETED, job.error_message
    assert names(settings.completed_dir / "other") == [destination.name]
    assert not exists(job_dir)


async def test_without_auto_resume_interrupted_jobs_fail(
    make_manager: Callable[..., JobManager],
    settings: Settings,
    new_job: Callable[..., Any],
    read_job: Callable[[str], Any],
) -> None:
    job_id = await new_job(status=JobStatus.DOWNLOADING)

    manager = make_manager(settings=settings.model_copy(update={"auto_resume": False}))
    await manager.start()
    try:
        job = await read_job(job_id)
    finally:
        await manager.stop()

    assert job.status == JobStatus.FAILED
    assert job.error_code == "interrupted"


# ------------------------------------------------------------------- AC10: retry


async def test_retry_after_a_failed_organize_does_not_download_again(
    manager: JobManager,
    settings: Settings,
    new_job: Callable[..., Any],
    read_job: Callable[[str], Any],
    fake_ytdlp: FakeYtdlp,
    media: dict[str, Path],
    hub: EventHub,
    db: Database,
) -> None:
    from app.jobs.service import JobService

    # A job that already downloaded, then failed while organizing.
    job_id = await new_job(
        status=JobStatus.FAILED,
        last_completed_step=Step.TRANSCODE,
        error_code="OrganizeError",
        error_message="Permission denied",
    )
    job_dir = settings.incomplete_dir / job_id
    job_dir.mkdir(parents=True)
    video = job_dir / "video.mkv"
    video.write_bytes(media["small"].read_bytes())
    (job_dir / "final_path").write_text(f"{video}\n")
    fake_ytdlp.downloads(media["small"])

    service = JobService(db, settings, hub, manager)
    await service.retry(job_id)
    job = await wait_for_status(read_job, job_id, *TERMINAL)

    assert job.status == JobStatus.COMPLETED, job.error_message
    assert fake_ytdlp.calls == []
    assert is_file(Path(job.completed_path))


# ------------------------------------------- M6 AC7: a TV request's jobs


async def test_tv_jobs_are_claimed_in_episode_order(
    make_manager: Callable[..., JobManager],
    new_job: Callable[..., Any],
    read_job: Callable[[str], Any],
) -> None:
    """AC7 (§6.1): oldest request first, then episode order inside a TV request."""
    # One `created_at` for the whole request, which is what `POST /api/requests` writes.
    moment = utcnow()
    first = await _tv_job(new_job, episode=3, created_at=moment)
    request_id = (await read_job(first)).request_id
    for episode in (1, 2):
        await _tv_job(new_job, episode=episode, created_at=moment, request_id=request_id)
    # Not started: the claim loop would race this test for the same rows.
    manager = make_manager()

    claimed = [await manager._claim() for _ in range(4)]

    assert [job.episode for job in claimed[:3]] == [1, 2, 3]
    assert {job.request_id for job in claimed[:3]} == {request_id}
    assert claimed[3] is None
    # The whole target comes back with the row, so the pipeline can name the file (§7.2).
    assert claimed[0].target() == Episode("Some Show", 1, 1, "Episode 1")


async def test_a_daily_tv_job_is_claimed_as_a_dated_episode(
    make_manager: Callable[..., JobManager], new_job: Callable[..., Any]
) -> None:
    """AC7: a daily series carries its air date into the naming target (§7.2)."""
    await _tv_job(
        new_job,
        episode=None,
        created_at=utcnow(),
        numbering="daily",
        season=2024,
        air_date=date(2024, 3, 15),
        episode_title="News",
    )
    manager = make_manager()

    claimed = await manager._claim()

    assert claimed is not None
    assert claimed.target() == DailyEpisode("Some Show", date(2024, 3, 15), "News", season=2024)


async def test_a_tv_request_summary_counts_each_finished_episode(
    manager: JobManager,
    hub: EventHub,
    new_job: Callable[..., Any],
    read_job: Callable[[str], Any],
    fake_ytdlp: FakeYtdlp,
    media: dict[str, Path],
) -> None:
    """AC7: `request.summary` reports 1/3, then 2/3, then 3/3 (§6, §12)."""
    fake_ytdlp.downloads(media["hd"])
    moment = utcnow()
    first = await _tv_job(new_job, episode=1, created_at=moment)
    request_id = (await read_job(first)).request_id
    jobs = [first] + [
        await _tv_job(new_job, episode=n, created_at=moment, request_id=request_id) for n in (2, 3)
    ]

    async with hub.subscribe() as events:
        manager.wake()
        # Awaited off the stream, not polled: `_finish` writes the terminal status before
        # it publishes the summary, so a job can be done with its event still in flight.
        summaries = await _summaries(events, request_id, len(jobs))

    assert [(s["completed"], s["total"]) for s in summaries] == [(1, 3), (2, 3), (3, 3)]
    assert {s["failed"] for s in summaries} == {0}
    for job_id in jobs:
        assert (await read_job(job_id)).status == JobStatus.COMPLETED


async def _summaries(
    events: asyncio.Queue[Any], request_id: str, wanted: int
) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    async with asyncio.timeout(60):
        while len(found) < wanted:
            event = await events.get()
            if event.type == "request.summary" and event.data["request_id"] == request_id:
                found.append(event.data)
    return found


async def _tv_job(new_job: Callable[..., Any], **fields: Any) -> str:
    """One episode of "Some Show", as `POST /api/requests` would insert it."""
    return await new_job(
        media_type="tv",
        title="Some Show",
        numbering=fields.pop("numbering", "standard"),
        sonarr_series_id=3,
        season=fields.pop("season", 1),
        episode_title=fields.pop("episode_title", None) or f"Episode {fields.get('episode')}",
        **fields,
    )


# ------------------------------- AC3: sidecar subtitles are organised next to the video


async def test_sidecar_subtitles_are_organised_next_to_the_video(
    manager: JobManager,
    settings: Settings,
    new_job: Callable[..., Any],
    read_job: Callable[[str], Any],
    fake_ytdlp: FakeYtdlp,
    media: dict[str, Path],
) -> None:
    fake_ytdlp.downloads(media["small"])
    options = DownloadOptions(
        quality="best",
        retries=0,
        subtitles=SubtitleOptions(mode="sidecar", languages=("en",)),
    )
    job_id = await new_job(options=options)
    manager.wake()

    job = await wait_for_status(read_job, job_id, *TERMINAL)

    assert job.status == JobStatus.COMPLETED, job.error_message
    video = settings.completed_dir / "other" / "Big Buck Bunny [abc123].mkv"
    subtitle = video.with_name("Big Buck Bunny [abc123].en.srt")
    assert Path(job.completed_path) == video
    assert job.sidecar_paths == [str(subtitle)]
    assert is_file(video)
    assert is_file(subtitle)
    assert not exists(settings.incomplete_dir / job_id)


async def test_embedded_subtitles_leave_no_sidecar(
    manager: JobManager,
    settings: Settings,
    new_job: Callable[..., Any],
    read_job: Callable[[str], Any],
    fake_ytdlp: FakeYtdlp,
    media: dict[str, Path],
) -> None:
    fake_ytdlp.downloads(media["small"])
    options = DownloadOptions(
        quality="best",
        retries=0,
        subtitles=SubtitleOptions(mode="embed", languages=("en",)),
    )
    job_id = await new_job(options=options)
    manager.wake()

    job = await wait_for_status(read_job, job_id, *TERMINAL)

    assert job.status == JobStatus.COMPLETED, job.error_message
    assert job.sidecar_paths == []
    assert names(settings.completed_dir / "other") == ["Big Buck Bunny [abc123].mkv"]
