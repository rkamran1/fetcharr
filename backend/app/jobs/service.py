"""Reads and user actions on jobs; the JobManager owns every pipeline write (§6.1)."""

import asyncio
import shutil
from pathlib import Path

from sqlalchemy import delete, select

from app.config import Settings
from app.db.base import utcnow
from app.db.session import Database
from app.events.service import EventHub
from app.jobs.constants import CANCELLABLE_STATUSES, JobStatus
from app.jobs.exceptions import CancelTooLate, JobNotFound, RetryNotPossible, UnsafePath
from app.jobs.manager import JobManager
from app.jobs.models import Job, JobLog
from app.jobs.schemas import JobList, JobLogRead, JobRead, LogLine
from app.jobs.utils import is_inside

#: The queue shows everything running plus the most recent finished jobs.
LIST_LIMIT = 50
LOG_LIMIT = 500


class JobService:
    def __init__(
        self, db: Database, settings: Settings, hub: EventHub, manager: JobManager
    ) -> None:
        self.db = db
        self.settings = settings
        self.hub = hub
        self.manager = manager

    async def get(self, job_id: str) -> JobRead:
        async with self.db.read_session() as session:
            job = await session.get(Job, job_id)
            if job is None:
                raise JobNotFound(job_id)
            return self.read(job)

    async def list(self) -> JobList:
        async with self.db.read_session() as session:
            jobs = list(
                await session.scalars(
                    select(Job).order_by(Job.created_at.desc(), Job.id).limit(LIST_LIMIT)
                )
            )
        return JobList(jobs=[self.read(job) for job in jobs])

    async def log(self, job_id: str) -> JobLogRead:
        async with self.db.read_session() as session:
            if await session.get(Job, job_id) is None:
                raise JobNotFound(job_id)
            rows = list(
                await session.scalars(
                    select(JobLog)
                    .where(JobLog.job_id == job_id)
                    .order_by(JobLog.id.desc())
                    .limit(LOG_LIMIT)
                )
            )
        rows.reverse()
        return JobLogRead(
            lines=[LogLine(ts=row.ts, level=row.level, line=row.line) for row in rows]
        )

    async def cancel(self, job_id: str) -> JobRead:
        """Ask a running job to stop, or finish a queued one straight away (§6.1)."""
        cancelled_dir: Path | None = None
        async with self.db.write_session() as session:
            job = await session.get(Job, job_id)
            if job is None:
                raise JobNotFound(job_id)
            if job.status not in CANCELLABLE_STATUSES:
                raise CancelTooLate(job.status)
            job.cancel_requested = True
            running = self.manager.request_cancel(job_id)
            if not running:
                # Nothing to signal: it never left the queue, so finish it here.
                job.status = JobStatus.CANCELLED
                job.phase = None
                job.cancel_requested = False
                job.finished_at = utcnow()
                cancelled_dir = Path(job.job_dir)
            read = self.read(job)
        if cancelled_dir is not None:
            await asyncio.to_thread(shutil.rmtree, cancelled_dir, True)
            self.hub.publish(
                "job.state", {"job_id": job_id, "status": JobStatus.CANCELLED, "phase": None}
            )
        return read

    async def retry(self, job_id: str) -> JobRead:
        """Put a failed job back in the queue; its checkpoint decides where it resumes."""
        async with self.db.write_session() as session:
            job = await session.get(Job, job_id)
            if job is None:
                raise JobNotFound(job_id)
            if job.status != JobStatus.FAILED:
                raise RetryNotPossible(job.status)
            job.status = JobStatus.QUEUED
            job.phase = None
            job.error_code = None
            job.error_message = None
            job.finished_at = None
            read = self.read(job)
        self.manager.wake()
        return read

    async def delete(self, job_id: str, delete_file: bool = False) -> None:
        """Remove the job, and its file when asked, but only inside fetcharr's folders."""
        async with self.db.read_session() as session:
            job = await session.get(Job, job_id)
            if job is None:
                raise JobNotFound(job_id)
            completed_path = Path(job.completed_path) if job.completed_path else None
            job_dir = Path(job.job_dir)

        if delete_file and completed_path is not None:
            if not is_inside(completed_path, self.settings.completed_dir, job_dir):
                raise UnsafePath(str(completed_path))
            await asyncio.to_thread(completed_path.unlink, True)
        if delete_file and is_inside(job_dir, self.settings.incomplete_dir):
            await asyncio.to_thread(shutil.rmtree, job_dir, True)

        async with self.db.write_session() as session:
            await session.execute(delete(JobLog).where(JobLog.job_id == job_id))
            await session.execute(delete(Job).where(Job.id == job_id))

    def read(self, job: Job) -> JobRead:
        """The stored row with the live progress snapshot on top (§3.1 rule 5)."""
        snapshot = self.hub.snapshot(job.id)
        return JobRead(
            id=job.id,
            request_id=job.request_id,
            url=job.url,
            source_title=job.source_title,
            thumbnail_url=job.thumbnail_url,
            duration=job.duration,
            status=job.status,
            phase=job.phase,
            attempt=job.attempt,
            progress_pct=snapshot.progress_pct if snapshot else job.progress_pct,
            downloaded_bytes=snapshot.downloaded_bytes if snapshot else job.downloaded_bytes,
            total_bytes=snapshot.total_bytes if snapshot else job.total_bytes,
            speed_bps=snapshot.speed_bps if snapshot else job.speed_bps,
            eta_s=snapshot.eta_s if snapshot else job.eta_s,
            completed_path=job.completed_path,
            file_size=job.file_size,
            import_status=job.import_status,
            error_code=job.error_code,
            error_message=job.error_message,
            created_at=job.created_at,
            started_at=job.started_at,
            finished_at=job.finished_at,
        )
