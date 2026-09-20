"""The episode import step against a mocked Sonarr and a real filesystem (§7.5, AC6, AC8–AC10).

Sonarr is mocked with respx, but the files are real: the mock deletes the video when it
accepts the command, which is exactly what "Sonarr moved it" looks like from here.
"""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from app.config import Settings
from app.db.session import Database
from app.events.service import EventHub
from app.jobs.constants import ImportStatus, JobStatus, Step
from app.jobs.manager import JobManager
from app.jobs.service import JobService
from tests.conftest import SONARR_API_KEY, SONARR_URL, exists, is_file, names
from tests.fake_ytdlp import FakeYtdlp
from tests.jobs.conftest import TERMINAL, wait_for_status

SERIES = "Some Show"
SERIES_ID = 3
SEASON = 1
EPISODE = 1
EPISODE_TITLE = "Pilot"
EPISODE_ID = 101
FILE_NAME = f"{SERIES} - S01E01 - {EPISODE_TITLE} WEBDL-720p.mkv"
LIBRARY_PATH = f"/library/tv-shows/{SERIES}/Season 1/{FILE_NAME}"
COMMAND_ID = 42
REJECTIONS = ("Not an upgrade for existing episode file(s)", "Sample")


@pytest.fixture
def settings(migrated_db_url: str, downloads_dir: Path, tmp_path: Path) -> Settings:
    """Sonarr configured from the environment, so no encryption is involved here (§7.5)."""
    return Settings(
        app_version="1.2.3",
        database_url=migrated_db_url,
        completed_dir=downloads_dir / "completed",
        incomplete_dir=downloads_dir / "incomplete",
        secret_key_file=tmp_path / "secret.key",
        sonarr_url=SONARR_URL,
        sonarr_api_key=SONARR_API_KEY,
    )


def tv_root(settings: Settings) -> Path:
    return settings.completed_dir / "tv-shows"


def series_folder(settings: Settings) -> Path:
    return tv_root(settings) / SERIES


def season_folder(settings: Settings) -> Path:
    return series_folder(settings) / f"Season {SEASON}"


def episode_file(settings: Settings) -> Path:
    return season_folder(settings) / FILE_NAME


# Sync on purpose: ruff's ASYNC240 forbids pathlib I/O inside an async test body.
def put_file(path: Path, content: bytes = b"a sibling download") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


async def new_episode_job(new_job: Callable[..., Any], **fields: Any) -> str:
    return await new_job(
        media_type="tv",
        title=SERIES,
        numbering="standard",
        sonarr_series_id=SERIES_ID,
        season=SEASON,
        episode=EPISODE,
        episode_title=EPISODE_TITLE,
        sonarr_episode_id=EPISODE_ID,
        **fields,
    )


def poll_route(mock: respx.Router, *statuses: str) -> Any:
    """`GET /command/{id}` answering each status in turn, then repeating the last one."""
    answers = list(statuses) or ["completed"]

    def answer(_request: httpx.Request) -> httpx.Response:
        status = answers.pop(0) if len(answers) > 1 else answers[0]
        return httpx.Response(200, json={"id": COMMAND_ID, "status": status})

    return mock.get(f"/api/v3/command/{COMMAND_ID}").mock(side_effect=answer)


def imports_the_file(*paths: Path) -> Callable[[httpx.Request], httpx.Response]:
    """A command mock that moves the file out of completed/, the way Sonarr does."""

    def scan(_request: httpx.Request) -> httpx.Response:
        for path in paths:
            path.unlink(missing_ok=True)
        return httpx.Response(201, json={"id": COMMAND_ID, "status": "queued"})

    return scan


def leaves_the_file(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(201, json={"id": COMMAND_ID, "status": "queued"})


def episode_route(mock: respx.Router, path: str | None = LIBRARY_PATH) -> Any:
    body = {"id": EPISODE_ID, "episodeFile": {"path": path}} if path else {"id": EPISODE_ID}
    return mock.get(f"/api/v3/episode/{EPISODE_ID}").mock(
        return_value=httpx.Response(200, json=body)
    )


def rejections_route(mock: respx.Router, *reasons: str) -> Any:
    body = [{"rejections": [{"reason": reason} for reason in reasons]}]
    return mock.get("/api/v3/manualimport").mock(return_value=httpx.Response(200, json=body))


# ------------------------------------------------------- AC6/AC8: the happy path


async def test_import_moves_the_episode_and_records_the_library_path(
    manager: JobManager,
    settings: Settings,
    new_job: Callable[..., Any],
    read_job: Callable[[str], Any],
    fake_ytdlp: FakeYtdlp,
    media: dict[str, Path],
) -> None:
    """AC8: the command §7.5 documents, then the verified library path back."""
    fake_ytdlp.downloads(media["hd"])
    job_id = await new_episode_job(new_job)

    async with respx.mock(base_url=SONARR_URL, assert_all_called=False) as mock:
        command = mock.post("/api/v3/command").mock(
            side_effect=imports_the_file(episode_file(settings))
        )
        polls = poll_route(mock, "queued", "completed")
        episode = episode_route(mock)
        manager.wake()
        job = await wait_for_status(read_job, job_id, *TERMINAL)

    assert job.status == JobStatus.COMPLETED, job.error_message
    assert job.import_status == ImportStatus.IMPORTED
    assert job.imported_path == LIBRARY_PATH
    assert job.imported_at is not None
    assert job.import_command_id == str(COMMAND_ID)
    assert job.import_attempts == 1
    assert job.last_completed_step == Step.IMPORT
    # §7.5 step 1: the episode's own file, not its folder.
    assert command.call_count == 1
    assert json.loads(command.calls[0].request.content) == {
        "name": "DownloadedEpisodesScan",
        "path": str(episode_file(settings)),
        "importMode": "Move",
    }
    assert polls.call_count == 2
    assert episode.call_count == 1
    # The season and series folders are empty now, so they go; `tv-shows` stays (§7.5 step 4).
    assert not exists(season_folder(settings))
    assert not exists(series_folder(settings))
    assert exists(tv_root(settings))


async def test_an_episode_lands_in_the_sonarr_layout(
    manager: JobManager,
    settings: Settings,
    new_job: Callable[..., Any],
    read_job: Callable[[str], Any],
    fake_ytdlp: FakeYtdlp,
    media: dict[str, Path],
) -> None:
    """AC6: Sonarr's series and episode titles, in `Season {season}`, with the quality (§7.2)."""
    fake_ytdlp.downloads(media["hd"])
    job_id = await new_episode_job(new_job)

    async with respx.mock(base_url=SONARR_URL, assert_all_called=False) as mock:
        mock.post("/api/v3/command").mock(side_effect=leaves_the_file)
        poll_route(mock, "completed")
        episode_route(mock)
        rejections_route(mock, *REJECTIONS)
        manager.wake()
        job = await wait_for_status(read_job, job_id, *TERMINAL)

    assert Path(job.completed_path) == episode_file(settings)
    assert is_file(episode_file(settings))
    assert names(season_folder(settings)) == [FILE_NAME]


async def test_a_pending_sibling_episode_keeps_the_season_folder(
    manager: JobManager,
    settings: Settings,
    new_job: Callable[..., Any],
    read_job: Callable[[str], Any],
    fake_ytdlp: FakeYtdlp,
    media: dict[str, Path],
) -> None:
    """AC8: pruning only ever removes a folder that is already empty (§7.5 step 4)."""
    fake_ytdlp.downloads(media["hd"])
    sibling = season_folder(settings) / f"{SERIES} - S01E02 - Second WEBDL-720p.mkv"
    put_file(sibling)
    job_id = await new_episode_job(new_job)

    async with respx.mock(base_url=SONARR_URL, assert_all_called=False) as mock:
        mock.post("/api/v3/command").mock(side_effect=imports_the_file(episode_file(settings)))
        poll_route(mock, "completed")
        episode_route(mock)
        manager.wake()
        job = await wait_for_status(read_job, job_id, *TERMINAL)

    assert job.import_status == ImportStatus.IMPORTED
    # The imported episode is gone, the un-imported one and both folders are not.
    assert names(season_folder(settings)) == [sibling.name]
    assert exists(series_folder(settings))


# ------------------------------------------------------------ AC9: rejections


async def test_a_rejected_episode_records_sonarrs_reasons(
    manager: JobManager,
    settings: Settings,
    new_job: Callable[..., Any],
    read_job: Callable[[str], Any],
    fake_ytdlp: FakeYtdlp,
    media: dict[str, Path],
) -> None:
    """AC9: Sonarr's own words, stored verbatim, and the job still completes (§6)."""
    fake_ytdlp.downloads(media["hd"])
    job_id = await new_episode_job(new_job)

    async with respx.mock(base_url=SONARR_URL, assert_all_called=False) as mock:
        command = mock.post("/api/v3/command").mock(side_effect=leaves_the_file)
        poll_route(mock, "completed")
        episode_route(mock)
        reasons = rejections_route(mock, *REJECTIONS, "Episode not found by air date")
        manager.wake()
        job = await wait_for_status(read_job, job_id, *TERMINAL)

    assert job.status == JobStatus.COMPLETED
    assert job.import_status == ImportStatus.NOT_IMPORTED
    assert job.import_detail == {
        "rejections": [*REJECTIONS, "Episode not found by air date"],
    }
    assert job.imported_path is None
    # A verdict isn't an error, so it is never retried (§6.1).
    assert command.call_count == 1
    assert reasons.calls[0].request.url.params["folder"] == str(season_folder(settings))
    # The file stays where a manual import can find it.
    assert is_file(episode_file(settings))


async def test_retry_import_imports_the_episode_without_downloading_again(
    manager: JobManager,
    settings: Settings,
    db: Database,
    hub: EventHub,
    new_job: Callable[..., Any],
    read_job: Callable[[str], Any],
    fake_ytdlp: FakeYtdlp,
    media: dict[str, Path],
) -> None:
    """AC9: once Sonarr accepts it, Retry import re-runs only the import step (§7.5)."""
    fake_ytdlp.downloads(media["hd"])
    job_id = await new_episode_job(new_job)

    async with respx.mock(base_url=SONARR_URL, assert_all_called=False) as mock:
        mock.post("/api/v3/command").mock(side_effect=leaves_the_file)
        poll_route(mock, "completed")
        episode_route(mock)
        rejections_route(mock, "Unknown series")
        manager.wake()
        rejected = await wait_for_status(read_job, job_id, *TERMINAL)

    assert rejected.import_status == ImportStatus.NOT_IMPORTED
    downloads = len(fake_ytdlp.calls)
    completed_path = rejected.completed_path

    # The owner has now added the series in Sonarr and presses Retry import.
    async with respx.mock(base_url=SONARR_URL, assert_all_called=False) as mock:
        mock.post("/api/v3/command").mock(side_effect=imports_the_file(episode_file(settings)))
        poll_route(mock, "completed")
        episode_route(mock)
        service = JobService(db, settings, hub, manager)
        read = await service.retry_import(job_id)
        assert read.import_status == ImportStatus.PENDING
        job = await wait_for_status(read_job, job_id, *TERMINAL)

    assert job.import_status == ImportStatus.IMPORTED
    assert job.imported_path == LIBRARY_PATH
    assert job.completed_path == completed_path
    # Nothing was downloaded or organised a second time (§6.1: it resumes at `import`).
    assert len(fake_ytdlp.calls) == downloads


# --------------------------------------------- AC10: the season-folder fallback


async def test_a_file_path_sonarr_refuses_falls_back_to_the_season_folder(
    manager: JobManager,
    settings: Settings,
    new_job: Callable[..., Any],
    read_job: Callable[[str], Any],
    read_logs: Callable[[str], Any],
    fake_ytdlp: FakeYtdlp,
    media: dict[str, Path],
) -> None:
    """AC10: a 400 on the file path is answered with the folder, not with a retry."""
    fake_ytdlp.downloads(media["hd"])
    job_id = await new_episode_job(new_job)
    answers = [
        httpx.Response(400, json={"propertyName": "path", "errorMessage": "Path is not a folder"})
    ]

    def scan(request: httpx.Request) -> httpx.Response:
        if answers:
            return answers.pop(0)
        episode_file(settings).unlink(missing_ok=True)
        return httpx.Response(201, json={"id": COMMAND_ID, "status": "queued"})

    async with respx.mock(base_url=SONARR_URL, assert_all_called=False) as mock:
        command = mock.post("/api/v3/command").mock(side_effect=scan)
        poll_route(mock, "completed")
        episode_route(mock)
        manager.wake()
        job = await wait_for_status(read_job, job_id, *TERMINAL)

    assert job.import_status == ImportStatus.IMPORTED
    assert job.imported_path == LIBRARY_PATH
    # Two commands, one attempt: the fallback is a second path, not a second try (§6.1).
    assert command.call_count == 2
    assert job.import_attempts == 1
    paths = [json.loads(call.request.content)["path"] for call in command.calls]
    assert paths == [str(episode_file(settings)), str(season_folder(settings))]
    assert any("refused the file path" in line for line in await read_logs(job_id))


async def test_a_folder_path_sonarr_refuses_is_not_retried_with_the_same_path(
    manager: JobManager,
    settings: Settings,
    new_job: Callable[..., Any],
    read_job: Callable[[str], Any],
    fake_ytdlp: FakeYtdlp,
    media: dict[str, Path],
) -> None:
    """A 4xx the fallback can't fix is a real error, and 4xx is never retried (§6.1)."""
    fake_ytdlp.downloads(media["hd"])
    job_id = await new_episode_job(new_job)

    async with respx.mock(base_url=SONARR_URL, assert_all_called=False) as mock:
        command = mock.post("/api/v3/command").mock(return_value=httpx.Response(400, text="no"))
        episode_route(mock)
        manager.wake()
        job = await wait_for_status(read_job, job_id, *TERMINAL)

    assert job.import_status == ImportStatus.ERROR
    assert "400" in job.import_detail["error"]
    # One attempt, two paths tried: the file, then the folder. Then it stops.
    assert command.call_count == 2
    assert job.import_attempts == 1


# ----------------------------------------- Sonarr isn't configured at all (§7.5)


async def test_an_episode_without_sonarr_configured_is_not_imported(
    make_manager: Callable[..., JobManager],
    settings: Settings,
    new_job: Callable[..., Any],
    read_job: Callable[[str], Any],
    fake_ytdlp: FakeYtdlp,
    media: dict[str, Path],
) -> None:
    """§7.5: an unconfigured app is a reason on the card, not a failed job."""
    fake_ytdlp.downloads(media["hd"])
    unconfigured = settings.model_copy(update={"sonarr_url": None, "sonarr_api_key": None})
    manager = make_manager(settings=unconfigured)
    await manager.start()
    job_id = await new_episode_job(new_job)

    try:
        manager.wake()
        job = await wait_for_status(read_job, job_id, *TERMINAL)
    finally:
        await manager.stop()

    assert job.status == JobStatus.COMPLETED
    assert job.import_status == ImportStatus.NOT_IMPORTED
    assert job.import_detail == {"rejections": ["Sonarr is not configured in Settings"]}
    assert is_file(episode_file(unconfigured))
