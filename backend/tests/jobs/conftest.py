import uuid
from collections.abc import AsyncIterator, Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from tenacity import wait_none

from app.config import Settings
from app.db.base import utcnow
from app.db.session import Database
from app.events.service import EventHub
from app.jobs.constants import ImportStatus, JobStatus
from app.jobs.manager import JobManager
from app.jobs.models import Job, JobLog
from app.requests.models import Request
from app.ytdlp.schemas import DownloadOptions

URL = "https://example.com/watch?v=abc123"


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
def make_manager(db: Database, settings: Settings, hub: EventHub) -> Callable[..., JobManager]:
    """A manager whose retries never sleep (§6.1: the wait strategy is injectable)."""
    managers: list[JobManager] = []

    def build(**overrides: Any) -> JobManager:
        manager = JobManager(
            overrides.pop("db", db),
            overrides.pop("settings", settings),
            overrides.pop("hub", hub),
            download_wait=wait_none(),
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
                        media_type="other",
                        title=title,
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
                    import_status=ImportStatus.NOT_APPLICABLE,
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
