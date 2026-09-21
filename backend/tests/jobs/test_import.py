"""The import step against a mocked Radarr and a real filesystem (§7.5, AC4–AC10, AC15).

Radarr is mocked with respx, but the files are real: the mock deletes the video when it
accepts the command, which is exactly what "Radarr moved it" looks like from here.
"""

import asyncio
import contextlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from tenacity import wait_none

from app.config import Settings
from app.db.session import Database
from app.events.service import EventHub
from app.integrations.arr import ImportPolicy
from app.jobs.constants import ImportStatus, JobStatus, Step
from app.jobs.exceptions import ImportNotPossible
from app.jobs.manager import JobManager
from app.jobs.service import JobService
from tests.conftest import RADARR_API_KEY, RADARR_URL, exists, is_file, names
from tests.fake_ytdlp import FakeYtdlp
from tests.jobs.conftest import TERMINAL, wait_for_status

TITLE = "Big Buck Bunny"
YEAR = 2008
MOVIE_ID = 7
FOLDER_NAME = f"{TITLE} ({YEAR})"
FILE_NAME = f"{TITLE} ({YEAR}) WEBDL-720p.mkv"
LIBRARY_PATH = f"/movies/{FOLDER_NAME}/{FILE_NAME}"
COMMAND_ID = 42
REJECTION = "Not an upgrade for existing movie file(s)"


@pytest.fixture
def settings(migrated_db_url: str, downloads_dir: Path, tmp_path: Path) -> Settings:
    """Radarr configured from the environment, so no encryption is involved here (§7.5)."""
    return Settings(
        app_version="1.2.3",
        database_url=migrated_db_url,
        completed_dir=downloads_dir / "completed",
        incomplete_dir=downloads_dir / "incomplete",
        secret_key_file=tmp_path / "secret.key",
        radarr_url=RADARR_URL,
        radarr_api_key=RADARR_API_KEY,
    )


def movie_folder(settings: Settings, name: str = FOLDER_NAME) -> Path:
    return settings.completed_dir / "movies" / name


def movie_file(settings: Settings) -> Path:
    return movie_folder(settings) / FILE_NAME


# Sync on purpose: ruff's ASYNC240 forbids pathlib I/O inside an async test body.
def make_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def put_file(path: Path, content: bytes = b"the older download") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def size_of(path: Path) -> int:
    return path.stat().st_size


def content_of(path: Path) -> bytes:
    return path.read_bytes()


def empty_folder(folder: Path) -> None:
    for child in folder.iterdir():
        child.unlink()


async def new_movie_job(new_job: Callable[..., Any], **fields: Any) -> str:
    return await new_job(
        media_type="movie", title=TITLE, year=YEAR, radarr_movie_id=MOVIE_ID, **fields
    )


def poll_route(mock: respx.Router, *statuses: str) -> Any:
    """`GET /command/{id}` answering each status in turn, then repeating the last one."""
    answers = list(statuses) or ["completed"]

    def answer(_request: httpx.Request) -> httpx.Response:
        status = answers.pop(0) if len(answers) > 1 else answers[0]
        return httpx.Response(200, json={"id": COMMAND_ID, "status": status})

    return mock.get(f"/api/v3/command/{COMMAND_ID}").mock(side_effect=answer)


def imports_the_file(*paths: Path) -> Callable[[httpx.Request], httpx.Response]:
    """A command mock that moves the file out of completed/, the way Radarr does."""

    def scan(_request: httpx.Request) -> httpx.Response:
        for path in paths:
            path.unlink(missing_ok=True)
        return httpx.Response(201, json={"id": COMMAND_ID, "status": "queued"})

    return scan


def leaves_the_file(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(201, json={"id": COMMAND_ID, "status": "queued"})


def movie_route(mock: respx.Router, path: str | None = LIBRARY_PATH, movie_id: int = MOVIE_ID):
    body = {"id": movie_id, "movieFile": {"path": path}} if path else {"id": movie_id}
    return mock.get(f"/api/v3/movie/{movie_id}").mock(return_value=httpx.Response(200, json=body))


def rejections_route(mock: respx.Router, *reasons: str) -> Any:
    body = [{"rejections": [{"reason": reason} for reason in reasons]}]
    return mock.get("/api/v3/manualimport").mock(return_value=httpx.Response(200, json=body))


# ------------------------------------------------ AC4/AC5: the happy path


async def test_import_moves_the_movie_and_records_the_library_path(
    manager: JobManager,
    settings: Settings,
    new_job: Callable[..., Any],
    read_job: Callable[[str], Any],
    fake_ytdlp: FakeYtdlp,
    media: dict[str, Path],
) -> None:
    fake_ytdlp.downloads(media["hd"])
    job_id = await new_movie_job(new_job)

    async with respx.mock(base_url=RADARR_URL, assert_all_called=False) as mock:
        command = mock.post("/api/v3/command").mock(
            side_effect=imports_the_file(movie_file(settings))
        )
        polls = poll_route(mock, "queued", "completed")
        movie = movie_route(mock)
        manager.wake()
        job = await wait_for_status(read_job, job_id, *TERMINAL)

    assert job.status == JobStatus.COMPLETED, job.error_message
    assert job.import_status == ImportStatus.IMPORTED
    assert job.imported_path == LIBRARY_PATH
    assert job.imported_at is not None
    assert job.import_command_id == str(COMMAND_ID)
    assert job.import_attempts == 1
    assert job.last_completed_step == Step.IMPORT
    # The command says what §7.5 step 1 says it should.
    assert command.call_count == 1
    assert json.loads(command.calls[0].request.content) == {
        "name": "DownloadedMoviesScan",
        "path": str(movie_folder(settings)),
        "importMode": "Move",
    }
    assert polls.call_count == 2
    assert movie.call_count == 1
    # The now-empty movie folder is cleaned up, but `movies/` itself stays (§7.5 step 4).
    assert not exists(movie_folder(settings))
    assert exists(settings.completed_dir / "movies")


async def test_a_movie_lands_in_the_radarr_layout(
    manager: JobManager,
    settings: Settings,
    new_job: Callable[..., Any],
    read_job: Callable[[str], Any],
    fake_ytdlp: FakeYtdlp,
    media: dict[str, Path],
) -> None:
    """AC4: Radarr's own title and year, and the quality read from the file (§7.2)."""
    fake_ytdlp.downloads(media["hd"])
    job_id = await new_movie_job(new_job)

    async with respx.mock(base_url=RADARR_URL, assert_all_called=False) as mock:
        mock.post("/api/v3/command").mock(side_effect=leaves_the_file)
        poll_route(mock, "completed")
        movie_route(mock)
        rejections_route(mock, REJECTION)
        manager.wake()
        job = await wait_for_status(read_job, job_id, *TERMINAL)

    assert Path(job.completed_path) == movie_file(settings)
    assert is_file(movie_file(settings))


# ------------------------------------------------------- AC6: a rejection


async def test_a_rejected_import_records_radarr_reasons(
    manager: JobManager,
    settings: Settings,
    new_job: Callable[..., Any],
    read_job: Callable[[str], Any],
    fake_ytdlp: FakeYtdlp,
    media: dict[str, Path],
) -> None:
    fake_ytdlp.downloads(media["hd"])
    job_id = await new_movie_job(new_job)

    async with respx.mock(base_url=RADARR_URL, assert_all_called=False) as mock:
        command = mock.post("/api/v3/command").mock(side_effect=leaves_the_file)
        poll_route(mock, "completed")
        movie_route(mock)
        rejections = rejections_route(mock, REJECTION)
        manager.wake()
        job = await wait_for_status(read_job, job_id, *TERMINAL)

    # A download that succeeded is never marked failed because the import failed (§6).
    assert job.status == JobStatus.COMPLETED
    assert job.import_status == ImportStatus.NOT_IMPORTED
    assert job.import_detail == {"rejections": [REJECTION]}
    assert job.imported_path is None
    assert is_file(movie_file(settings))
    # A rejection is a verdict, not an error: it is never retried (§6.1).
    assert command.call_count == 1
    assert rejections.call_count == 1


async def test_a_sample_rejection_is_explained_in_the_log_and_the_detail(
    manager: JobManager,
    settings: Settings,
    new_job: Callable[..., Any],
    read_job: Callable[[str], Any],
    read_logs: Callable[[str], Any],
    fake_ytdlp: FakeYtdlp,
    media: dict[str, Path],
) -> None:
    """AC16: Radarr's bare "Sample" becomes a sentence saying why, and what to do instead."""
    fake_ytdlp.downloads(media["hd"])  # a one-second clip
    job_id = await new_movie_job(new_job)
    body = [
        {
            "movie": {"id": MOVIE_ID, "title": TITLE, "year": YEAR, "runtime": 10},
            "rejections": [{"reason": "Sample", "type": "permanent"}],
        }
    ]

    async with respx.mock(base_url=RADARR_URL, assert_all_called=False) as mock:
        mock.post("/api/v3/command").mock(side_effect=leaves_the_file)
        poll_route(mock, "completed")
        movie_route(mock)
        mock.get("/api/v3/manualimport").mock(return_value=httpx.Response(200, json=body))
        manager.wake()
        job = await wait_for_status(read_job, job_id, *TERMINAL)

    expected = (
        "the file is 0:01 long but Big Buck Bunny runs 10 min, so Radarr takes it for a "
        "sample or trailer, not the movie itself. Pick the full-length video, or download "
        "clips and trailers as Other."
    )
    assert job.import_status == ImportStatus.NOT_IMPORTED
    # Radarr's own word is kept verbatim; the explanation sits next to it.
    assert job.import_detail == {"rejections": ["Sample"], "explanation": expected}
    logs = await read_logs(job_id)
    assert f"Radarr did not import the file: Sample — {expected}" in logs


async def test_a_movie_without_radarr_configured_is_not_imported(
    make_manager: Callable[..., JobManager],
    settings: Settings,
    new_job: Callable[..., Any],
    read_job: Callable[[str], Any],
    fake_ytdlp: FakeYtdlp,
    media: dict[str, Path],
) -> None:
    fake_ytdlp.downloads(media["hd"])
    bare = settings.model_copy(update={"radarr_url": None, "radarr_api_key": None})
    manager = make_manager(settings=bare)
    await manager.start()
    job_id = await new_movie_job(new_job)

    try:
        # No routes at all: any HTTP call would fail the test outright.
        async with respx.mock(base_url=RADARR_URL, assert_all_called=False):
            manager.wake()
            job = await wait_for_status(read_job, job_id, *TERMINAL)
    finally:
        await manager.stop()

    assert job.status == JobStatus.COMPLETED
    assert job.import_status == ImportStatus.NOT_IMPORTED
    assert job.import_detail == {"rejections": ["Radarr is not configured in Settings"]}
    assert is_file(movie_file(settings))


# --------------------------------------------------- AC7: the retry policy


@pytest.mark.parametrize(
    ("name", "kind"),
    [("transport", "transport"), ("server", "server")],
)
async def test_transport_errors_and_5xx_are_retried_then_error(
    manager: JobManager,
    settings: Settings,
    new_job: Callable[..., Any],
    read_job: Callable[[str], Any],
    read_logs: Callable[[str], Any],
    fake_ytdlp: FakeYtdlp,
    media: dict[str, Path],
    name: str,
    kind: str,
) -> None:
    fake_ytdlp.downloads(media["hd"])
    job_id = await new_movie_job(new_job)
    failure: Any = (
        httpx.ConnectError("no route to host")
        if kind == "transport"
        else httpx.Response(503, text="Radarr is restarting")
    )

    async with respx.mock(base_url=RADARR_URL, assert_all_called=False) as mock:
        command = mock.post("/api/v3/command").mock(
            side_effect=failure if kind == "transport" else None,
            return_value=None if kind == "transport" else failure,
        )
        manager.wake()
        job = await wait_for_status(read_job, job_id, *TERMINAL)

    assert job.status == JobStatus.COMPLETED
    assert job.import_status == ImportStatus.ERROR
    assert job.import_attempts == 4
    assert command.call_count == 4
    assert is_file(movie_file(settings))
    # Every attempt is logged (§6.1).
    logs = await read_logs(job_id)
    for number in (1, 2, 3, 4):
        assert any(f"import attempt {number}" in line for line in logs), (number, logs)


async def test_a_polling_timeout_is_retried_then_errors(
    make_manager: Callable[..., JobManager],
    new_job: Callable[..., Any],
    read_job: Callable[[str], Any],
    fake_ytdlp: FakeYtdlp,
    media: dict[str, Path],
) -> None:
    fake_ytdlp.downloads(media["hd"])
    # A command that never leaves the queue, with no time left to wait for it.
    manager = make_manager(
        import_policy=ImportPolicy(
            wait=wait_none(), attempts=4, poll_interval=0.0, command_timeout=0.0
        )
    )
    await manager.start()
    job_id = await new_movie_job(new_job)

    try:
        async with respx.mock(base_url=RADARR_URL, assert_all_called=False) as mock:
            command = mock.post("/api/v3/command").mock(side_effect=leaves_the_file)
            poll_route(mock, "queued")
            manager.wake()
            job = await wait_for_status(read_job, job_id, *TERMINAL)
    finally:
        await manager.stop()

    assert job.import_status == ImportStatus.ERROR
    assert job.import_attempts == 4
    assert command.call_count == 4
    assert "still queued" in json.dumps(job.import_detail)


async def test_a_bad_api_key_is_not_retried(
    manager: JobManager,
    new_job: Callable[..., Any],
    read_job: Callable[[str], Any],
    fake_ytdlp: FakeYtdlp,
    media: dict[str, Path],
) -> None:
    fake_ytdlp.downloads(media["hd"])
    job_id = await new_movie_job(new_job)

    async with respx.mock(base_url=RADARR_URL, assert_all_called=False) as mock:
        command = mock.post("/api/v3/command").mock(return_value=httpx.Response(401))
        manager.wake()
        job = await wait_for_status(read_job, job_id, *TERMINAL)

    assert job.import_status == ImportStatus.ERROR
    assert job.import_attempts == 1
    assert command.call_count == 1
    assert job.import_detail is not None
    assert job.import_detail["hint"] == "check the API key in Settings"


# ------------------------------------------------------ AC8: retry import


async def test_retry_import_imports_without_downloading_again(
    manager: JobManager,
    settings: Settings,
    db: Database,
    hub: EventHub,
    new_job: Callable[..., Any],
    read_job: Callable[[str], Any],
    fake_ytdlp: FakeYtdlp,
    media: dict[str, Path],
) -> None:
    fake_ytdlp.downloads(media["hd"])
    job_id = await new_movie_job(new_job)

    async with respx.mock(base_url=RADARR_URL, assert_all_called=False) as mock:
        mock.post("/api/v3/command").mock(side_effect=leaves_the_file)
        poll_route(mock, "completed")
        movie_route(mock)
        rejections_route(mock, "Unknown movie")
        manager.wake()
        rejected = await wait_for_status(read_job, job_id, *TERMINAL)

    assert rejected.import_status == ImportStatus.NOT_IMPORTED
    downloads = len(fake_ytdlp.calls)
    completed_path = rejected.completed_path

    # The owner has now added the movie in Radarr and presses Retry import.
    async with respx.mock(base_url=RADARR_URL, assert_all_called=False) as mock:
        mock.post("/api/v3/command").mock(side_effect=imports_the_file(movie_file(settings)))
        poll_route(mock, "completed")
        movie_route(mock)
        service = JobService(db, settings, hub, manager)
        read = await service.retry_import(job_id)
        assert read.import_status == ImportStatus.PENDING
        job = await wait_for_status(read_job, job_id, *TERMINAL)

    assert job.import_status == ImportStatus.IMPORTED
    assert job.imported_path == LIBRARY_PATH
    assert job.completed_path == completed_path
    # Nothing was downloaded or organised a second time (§6.1: it resumes at `import`).
    assert len(fake_ytdlp.calls) == downloads


async def test_retry_import_is_refused_once_the_file_is_imported(
    manager: JobManager,
    settings: Settings,
    db: Database,
    hub: EventHub,
    new_job: Callable[..., Any],
) -> None:
    service = JobService(db, settings, hub, manager)
    imported = await new_movie_job(new_job, import_status=ImportStatus.IMPORTED)
    other = await new_job()

    for job_id in (imported, other):
        with pytest.raises(ImportNotPossible):
            await service.retry_import(job_id)


# ---------------------------------------------------- AC9: restart recovery


async def test_recovery_verifies_before_sending_another_command(
    manager: JobManager,
    settings: Settings,
    new_job: Callable[..., Any],
    read_job: Callable[[str], Any],
    fake_ytdlp: FakeYtdlp,
) -> None:
    """The command went out, then fetcharr died. Radarr already did the work (§6.1)."""
    fake_ytdlp.downloads()
    folder = movie_folder(settings)
    make_dir(folder)
    job_id = await new_movie_job(
        new_job,
        last_completed_step=Step.ORGANIZE,
        completed_path=str(movie_file(settings)),
        import_status=ImportStatus.PENDING,
    )

    async with respx.mock(base_url=RADARR_URL, assert_all_called=False) as mock:
        command = mock.post("/api/v3/command")
        movie = movie_route(mock)
        manager.wake()
        job = await wait_for_status(read_job, job_id, *TERMINAL)

    assert job.import_status == ImportStatus.IMPORTED
    assert job.imported_path == LIBRARY_PATH
    assert command.call_count == 0
    assert movie.call_count == 1
    assert fake_ytdlp.calls == []
    assert not exists(folder)


# -------------------------------------------------- AC10: the per-app lock


async def test_two_movie_imports_are_serialised(
    manager: JobManager,
    settings: Settings,
    new_job: Callable[..., Any],
    read_job: Callable[[str], Any],
    fake_ytdlp: FakeYtdlp,
    media: dict[str, Path],
) -> None:
    fake_ytdlp.downloads(media["hd"])
    first = await new_movie_job(new_job)
    second = await new_job(
        media_type="movie", title="Sintel", year=2010, radarr_movie_id=9, video_id="sintel"
    )
    running = 0
    peak = 0
    entered = 0
    contended = False

    async def both_importing() -> None:
        async with asyncio.timeout(3):
            while True:
                statuses = [(await read_job(job)).status for job in (first, second)]
                if statuses.count(JobStatus.IMPORTING) == 2:
                    return
                await asyncio.sleep(0.01)

    async def scan(request: httpx.Request) -> httpx.Response:
        nonlocal running, peak, entered, contended
        running += 1
        entered += 1
        peak = max(peak, running)
        if entered == 1:
            # Hold the lock until the other job is also in the import step, so the
            # test really contends for it rather than just running fast enough.
            with contextlib.suppress(TimeoutError):
                await both_importing()
                contended = True
        folder = Path(json.loads(request.content)["path"])
        await asyncio.to_thread(empty_folder, folder)
        running -= 1
        return httpx.Response(201, json={"id": COMMAND_ID, "status": "queued"})

    async with respx.mock(base_url=RADARR_URL, assert_all_called=False) as mock:
        command = mock.post("/api/v3/command").mock(side_effect=scan)
        poll_route(mock, "completed")
        movie_route(mock)
        movie_route(mock, path="/movies/Sintel (2010)/Sintel (2010) WEBDL-720p.mkv", movie_id=9)
        manager.wake()
        jobs = [
            await wait_for_status(read_job, first, *TERMINAL),
            await wait_for_status(read_job, second, *TERMINAL),
        ]

    assert [job.import_status for job in jobs] == [ImportStatus.IMPORTED] * 2
    assert command.call_count == 2
    # One command at a time per arr app (§6.1): the second job was in the import step
    # while the first held the lock, and still its command went out on its own.
    assert contended is True
    assert peak == 1


# ------------------------------------------------ AC15: the collision policy


async def test_replace_moves_the_existing_file_aside(
    manager: JobManager,
    settings: Settings,
    new_job: Callable[..., Any],
    read_job: Callable[[str], Any],
    fake_ytdlp: FakeYtdlp,
    media: dict[str, Path],
) -> None:
    fake_ytdlp.downloads(media["hd"])
    put_file(movie_file(settings))
    job_id = await new_movie_job(new_job, collision_policy="replace")

    async with respx.mock(base_url=RADARR_URL, assert_all_called=False) as mock:
        mock.post("/api/v3/command").mock(side_effect=leaves_the_file)
        poll_route(mock, "completed")
        movie_route(mock)
        rejections_route(mock, REJECTION)
        manager.wake()
        job = await wait_for_status(read_job, job_id, *TERMINAL)

    assert Path(job.completed_path) == movie_file(settings)
    assert size_of(movie_file(settings)) > len(b"the older download")
    assert names(movie_folder(settings)) == [FILE_NAME]
    assert names(settings.incomplete_dir / "_replaced" / job_id) == [FILE_NAME]


async def test_keep_both_numbers_the_new_file(
    manager: JobManager,
    settings: Settings,
    new_job: Callable[..., Any],
    read_job: Callable[[str], Any],
    fake_ytdlp: FakeYtdlp,
    media: dict[str, Path],
) -> None:
    fake_ytdlp.downloads(media["hd"])
    put_file(movie_file(settings))
    job_id = await new_movie_job(new_job, collision_policy="keep_both")

    async with respx.mock(base_url=RADARR_URL, assert_all_called=False) as mock:
        mock.post("/api/v3/command").mock(side_effect=leaves_the_file)
        poll_route(mock, "completed")
        movie_route(mock)
        rejections_route(mock, REJECTION)
        manager.wake()
        job = await wait_for_status(read_job, job_id, *TERMINAL)

    numbered = f"{TITLE} ({YEAR}) WEBDL-720p (1).mkv"
    assert Path(job.completed_path).name == numbered
    assert names(movie_folder(settings)) == sorted([FILE_NAME, numbered])
    assert content_of(movie_file(settings)) == b"the older download"
