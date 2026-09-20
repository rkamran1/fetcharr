import asyncio
import uuid
from collections.abc import AsyncIterator, Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select
from tenacity import wait_none

from app.config import Settings
from app.db.base import utcnow
from app.db.session import Database
from app.events.service import EventHub
from app.integrations.arr import ImportPolicy, RadarrClient, SonarrClient
from app.jobs.constants import ImportStatus, JobStatus
from app.jobs.manager import JobManager
from app.jobs.models import Job, JobLog
from app.requests.models import Request
from app.settings.service import SettingsService
from app.ytdlp.schemas import DownloadOptions

URL = "https://example.com/watch?v=abc123"
TERMINAL = (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED)
#: The import policy under test never sleeps and never waits ten minutes (§6.1).
TEST_IMPORT_POLICY = ImportPolicy(
    wait=wait_none(), attempts=4, poll_interval=0.0, command_timeout=1.0
)


@pytest.fixture
async def db(migrated_db_url: str) -> AsyncIterator[Database]:
    database = Database(migrated_db_url)
    try:
        yield database
    finally:
        await database.dispose()


@pytest.fixture
def hub() -> EventHub:
    return EventHub()


@pytest.fixture
def secret_key() -> bytes:
    return Fernet.generate_key()


@pytest.fixture
async def radarr() -> AsyncIterator[RadarrClient]:
    client = RadarrClient()
    try:
        yield client
    finally:
        await client.aclose()


@pytest.fixture
async def sonarr() -> AsyncIterator[SonarrClient]:
    client = SonarrClient()
    try:
        yield client
    finally:
        await client.aclose()


@pytest.fixture
def make_manager(
    db: Database,
    settings: Settings,
    hub: EventHub,
    radarr: RadarrClient,
    sonarr: SonarrClient,
    secret_key: bytes,
) -> Callable[..., JobManager]:
    """A manager whose retries never sleep (§6.1: the wait strategy is injectable)."""
    managers: list[JobManager] = []

    def build(**overrides: Any) -> JobManager:
        chosen_db = overrides.pop("db", db)
        chosen_settings = overrides.pop("settings", settings)
        manager = JobManager(
            chosen_db,
            chosen_settings,
            overrides.pop("hub", hub),
            SettingsService(chosen_db, chosen_settings, secret_key),
            overrides.pop("radarr", radarr),
            overrides.pop("sonarr", sonarr),
            download_wait=wait_none(),
            import_policy=overrides.pop("import_policy", TEST_IMPORT_POLICY),
        )
        managers.append(manager)
        return manager

    return build


@pytest.fixture
async def manager(make_manager: Callable[..., JobManager]) -> AsyncIterator[JobManager]:
    instance = make_manager()
    await instance.start()
    try:
        yield instance
    finally:
        await instance.stop()


@pytest.fixture
def new_job(db: Database, settings: Settings) -> Callable[..., Any]:
    """Insert a request and one queued job, as `POST /api/requests` would."""

    async def insert(
        *,
        url: str = URL,
        title: str = "Big Buck Bunny",
        video_id: str = "abc123",
        options: DownloadOptions | None = None,
        request_id: str | None = None,
        created_at: datetime | None = None,
        media_type: str = "other",
        year: int | None = None,
        numbering: str | None = None,
        radarr_movie_id: int | None = None,
        sonarr_series_id: int | None = None,
        **fields: Any,
    ) -> str:
        job_id = str(uuid.uuid4())
        chosen = options or DownloadOptions(quality="best", retries=0)
        moment = created_at or utcnow()
        async with db.write_session() as session:
            if request_id is None:
                request_id = str(uuid.uuid4())
                session.add(
                    Request(
                        id=request_id,
                        media_type=media_type,
                        title=title,
                        year=year,
                        numbering=numbering,
                        radarr_movie_id=radarr_movie_id,
                        sonarr_series_id=sonarr_series_id,
                        options=chosen.model_dump(),
                        created_at=moment,
                    )
                )
                await session.flush()
            session.add(
                Job(
                    id=job_id,
                    request_id=request_id,
                    url=url,
                    video_id=video_id,
                    stream_type="http",
                    source_title=title,
                    status=fields.pop("status", JobStatus.QUEUED),
                    step_timings=fields.pop("step_timings", {}),
                    sidecar_paths=[],
                    collision_policy=fields.pop("collision_policy", "keep_both"),
                    import_status=fields.pop(
                        "import_status",
                        ImportStatus.NOT_APPLICABLE
                        if media_type == "other"
                        else ImportStatus.PENDING,
                    ),
                    max_attempts=chosen.retries + 1,
                    job_dir=str(settings.incomplete_dir / job_id),
                    created_at=moment,
                    **fields,
                )
            )
        return job_id

    return insert


@pytest.fixture
def read_job(db: Database) -> Callable[[str], Any]:
    async def read(job_id: str) -> Job:
        async with db.read_session() as session:
            job = await session.get(Job, job_id)
            assert job is not None
            return job

    return read


@pytest.fixture
def read_logs(db: Database) -> Callable[[str], Any]:
    async def read(job_id: str) -> list[str]:
        async with db.read_session() as session:
            rows = await session.scalars(
                select(JobLog).where(JobLog.job_id == job_id).order_by(JobLog.id)
            )
        return [row.line for row in rows]

    return read


def job_dir_of(settings: Settings, job_id: str) -> Path:
    return settings.incomplete_dir / job_id


async def wait_for_status(read_job: Callable[[str], Any], job_id: str, *statuses: str) -> Any:
    """Poll the row until the manager has written one of these statuses."""
    async with asyncio.timeout(30):
        while True:
            job = await read_job(job_id)
            if job.status in statuses:
                return job
            await asyncio.sleep(0.02)
