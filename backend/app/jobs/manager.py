"""The JobManager: claims queued jobs, runs one asyncio task each, and owns every write.

It is the only writer of pipeline state (requirements §6.1). Progress is published from
memory on every line and written to the database at most every two seconds (§3.1 rule 5),
and log lines are batched into one insert about once a second.
"""

import asyncio
import contextlib
import shutil
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, update

from app.config import Settings
from app.db.base import utcnow
from app.db.session import Database
from app.events.service import EventHub
from app.integrations.arr import ImportPolicy, RadarrClient
from app.jobs.constants import ACTIVE_STATUSES, JobStatus, Step
from app.jobs.models import Job, JobLog
from app.jobs.pipeline import PipelineContext, execute
from app.jobs.utils import as_stream_type
from app.library.naming import Movie, Other, Target
from app.library.organizer import CollisionPolicy
from app.requests.models import Request
from app.settings.service import SettingsService
from app.ytdlp.runner import DOWNLOAD_WAIT, DownloadCancelled, Progress, YtDlpFatal
from app.ytdlp.runtime import JsRuntime, detect_js_runtime
from app.ytdlp.schemas import DownloadOptions

#: At most one progress write per job in this window (§3.1 rule 5).
PROGRESS_DB_INTERVAL_S = 2.0
#: Log lines are buffered in memory and inserted in batches this often.
LOG_FLUSH_INTERVAL_S = 1.0
LOG_BUFFER_LINES = 500


@dataclass(frozen=True)
class _Claimed:
    """The job fields the pipeline needs, read once so no session stays open."""

    id: str
    request_id: str
    url: str
    source_title: str
    video_id: str
    stream_type: str
    job_dir: Path
    options: DownloadOptions
    last_completed_step: Step | None
    completed_path: Path | None
    collision_policy: str
    import_status: str
    media_type: str
    title: str | None
    year: int | None
    radarr_movie_id: int | None

    def target(self) -> Target:
        """Radarr's own title and year for a movie, the video's own title for other (§7.2)."""
        if self.media_type == "movie":
            return Movie(title=self.title or self.source_title, year=self.year)
        return Other(title=self.source_title, id=self.video_id)


class JobManager:
    def __init__(
        self,
        db: Database,
        settings: Settings,
        hub: EventHub,
        settings_service: SettingsService,
        radarr: RadarrClient,
        *,
        download_wait: Any = DOWNLOAD_WAIT,
        import_policy: ImportPolicy | None = None,
    ) -> None:
        self.db = db
        self.settings = settings
        self.hub = hub
        self.settings_service = settings_service
        self.radarr = radarr
        self.download_wait = download_wait
        self.import_policy = import_policy or ImportPolicy()
        self.aria2c_available = False
        self.js_runtime: JsRuntime | None = None
        self._slot = asyncio.Semaphore(settings.max_concurrent_downloads)
        self._wake = asyncio.Event()
        self._cancels: dict[str, asyncio.Event] = {}
        self._jobs: dict[str, asyncio.Task[None]] = {}
        self._writes: set[asyncio.Task[None]] = set()
        self._loop: asyncio.Task[None] | None = None

    # ---------------------------------------------------------------- lifecycle

    async def start(self) -> None:
        # Both touch the filesystem, so they run once, off the event loop (M2's note).
        self.js_runtime, self.aria2c_available = await asyncio.to_thread(_detect_tools)
        await self.recover()
        self._loop = asyncio.create_task(self._run_loop())
        self.wake()

    async def stop(self) -> None:
        for task in [self._loop, *self._jobs.values(), *self._writes]:
            if task is not None:
                task.cancel()
        pending = [t for t in [self._loop, *self._jobs.values(), *self._writes] if t is not None]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        self._loop = None
        self._jobs.clear()
        self._writes.clear()

    def wake(self) -> None:
        """Tell the claim loop there may be new work."""
        self._wake.set()

    def request_cancel(self, job_id: str) -> bool:
        """Signal a running job; False when this manager isn't running it."""
        event = self._cancels.get(job_id)
        if event is None:
            return False
        event.set()
        return True

    async def drain(self) -> None:
        """Wait for every job this manager has started (tests and shutdown)."""
        while self._jobs:
            await asyncio.gather(*list(self._jobs.values()), return_exceptions=True)

    # ------------------------------------------------------------------- claim

    async def _run_loop(self) -> None:
        while True:
            await self._wake.wait()
            self._wake.clear()
            while (job := await self._claim()) is not None:
                self._start(job)

    async def _claim(self) -> _Claimed | None:
        """One short BEGIN IMMEDIATE: take the oldest queued job and mark it starting."""
        async with self.db.write_session() as session:
            row = (
                await session.execute(
                    select(Job, Request)
                    .join(Request, Request.id == Job.request_id)
                    .where(Job.status == JobStatus.QUEUED)
                    .order_by(Request.created_at, Job.created_at, Job.id)
                    .limit(1)
                )
            ).first()
            if row is None:
                return None
            job, request = row
            job.status = JobStatus.STARTING
            job.phase = None
            job.error_code = None
            job.error_message = None
            if job.started_at is None:
                job.started_at = utcnow()
            claimed = _Claimed(
                id=job.id,
                request_id=job.request_id,
                url=job.url,
                source_title=job.source_title or job.url,
                video_id=job.video_id or "",
                stream_type=job.stream_type or "http",
                job_dir=Path(job.job_dir),
                options=DownloadOptions(**request.options),
                last_completed_step=Step(job.last_completed_step)
                if job.last_completed_step
                else None,
                completed_path=Path(job.completed_path) if job.completed_path else None,
                collision_policy=job.collision_policy,
                import_status=job.import_status,
                media_type=request.media_type,
                title=request.title,
                year=request.year,
                radarr_movie_id=request.radarr_movie_id,
            )
        self.hub.publish(
            "job.state", {"job_id": claimed.id, "status": JobStatus.STARTING, "phase": None}
        )
        return claimed

    def _start(self, job: _Claimed) -> None:
        self._cancels[job.id] = asyncio.Event()
        task = asyncio.create_task(self._run_job(job))
        self._jobs[job.id] = task
        task.add_done_callback(lambda _task: self._forget(job.id))

    def _forget(self, job_id: str) -> None:
        self._jobs.pop(job_id, None)
        self._cancels.pop(job_id, None)
        self.hub.forget(job_id)

    # -------------------------------------------------------------- one job

    async def _run_job(self, job: _Claimed) -> None:
        cancel = self._cancels[job.id]
        lines: deque[str] = deque(maxlen=LOG_BUFFER_LINES)
        last_progress_write = 0.0
        postprocessing = False

        def on_log(line: str) -> None:
            lines.append(line)

        def on_progress(progress: Progress) -> None:
            nonlocal last_progress_write, postprocessing
            self.hub.publish("job.progress", _progress_event(job.id, progress))
            if progress.postprocessing and not postprocessing:
                postprocessing = True
                self._spawn(self._set_status(job.id, JobStatus.POSTPROCESSING, Step.DOWNLOAD))
            now = asyncio.get_running_loop().time()
            if now - last_progress_write >= PROGRESS_DB_INTERVAL_S:
                last_progress_write = now
                self._spawn(self._write_progress(job.id, progress))

        def on_attempt(number: int) -> None:
            self._spawn(self._write_attempt(job.id, number))

        # Resolved before the step starts, so no transaction spans the call to Radarr (§3.1).
        connection = await self.settings_service.radarr() if job.media_type == "movie" else None

        context = PipelineContext(
            job_id=job.id,
            url=job.url,
            options=job.options,
            stream_type=as_stream_type(job.stream_type),
            target=job.target(),
            job_dir=job.job_dir,
            completed_dir=self.settings.completed_dir,
            incomplete_dir=self.settings.incomplete_dir,
            cancel=cancel,
            download_slot=self._slot,
            checkpoint=lambda step, seconds, fields: self._checkpoint(
                job.id, step, seconds, fields
            ),
            set_status=lambda status, step: self._set_status(job.id, status, step),
            on_progress=on_progress,
            on_log=on_log,
            on_attempt=on_attempt,
            aria2c_available=self.aria2c_available,
            js_runtime=self.js_runtime,
            last_completed_step=job.last_completed_step,
            completed_path=job.completed_path,
            collision_policy=CollisionPolicy(job.collision_policy),
            import_status=job.import_status,
            radarr_movie_id=job.radarr_movie_id,
            radarr=self.radarr,
            radarr_connection=connection,
            import_policy=self.import_policy,
            download_wait=self.download_wait,
        )

        flusher = asyncio.create_task(self._flush_logs_forever(job.id, lines))
        cancelled = False
        failure: tuple[str, str] | None = None
        try:
            await asyncio.to_thread(job.job_dir.mkdir, parents=True, exist_ok=True)
            await execute(context)
        except DownloadCancelled:
            cancelled = True
        except asyncio.CancelledError:
            # Shutdown: leave the row as it is, restart recovery picks it up (§6.1).
            raise
        except YtDlpFatal as error:
            failure = (error.kind, error.message)
            on_log(f"failed: {error.message}")
        except Exception as error:  # noqa: BLE001 - the job fails with whatever went wrong
            failure = (type(error).__name__, str(error))
            on_log(f"failed: {error}")
        finally:
            flusher.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await flusher

        # The log is complete before the terminal state is published, so a client that
        # sees `failed` can already read why.
        await self._flush_logs(job.id, lines)
        if cancelled:
            await self._cancelled(job.id, job.job_dir)
        elif failure is not None:
            await self._finish(job.id, JobStatus.FAILED, *failure)
        else:
            await self._finish(job.id, JobStatus.COMPLETED)

    # ------------------------------------------------------------------ writes

    def _spawn(self, coroutine: Any) -> None:
        """Run a short write in the background; the caller is a sync runner callback."""
        task = asyncio.create_task(coroutine)
        self._writes.add(task)
        task.add_done_callback(self._writes.discard)

    async def _update(self, job_id: str, values: dict[str, Any]) -> None:
        async with self.db.write_session() as session:
            await session.execute(update(Job).where(Job.id == job_id).values(**values))

    async def _write_progress(self, job_id: str, progress: Progress) -> None:
        await self._update(
            job_id,
            {
                "progress_pct": progress.pct,
                "downloaded_bytes": progress.downloaded_bytes,
                "total_bytes": progress.total_bytes,
                "speed_bps": progress.speed_bps,
                "eta_s": progress.eta_s,
            },
        )

    async def _write_attempt(self, job_id: str, number: int) -> None:
        await self._update(job_id, {"attempt": number})

    async def _set_status(self, job_id: str, status: JobStatus, step: Step) -> None:
        await self._update(job_id, {"status": status, "phase": step})
        self.hub.publish("job.state", {"job_id": job_id, "status": status, "phase": step})

    async def _checkpoint(
        self, job_id: str, step: Step, seconds: float, fields: dict[str, Any]
    ) -> None:
        async with self.db.write_session() as session:
            job = await session.get(Job, job_id)
            if job is None:  # pragma: no cover - deleted mid-run
                return
            timings = dict(job.step_timings or {})
            timings[step] = round(seconds, 3)
            job.step_timings = timings
            job.last_completed_step = step
            for name, value in fields.items():
                setattr(job, name, value)
        if "import_status" in fields:
            self.hub.publish(
                "job.import",
                {
                    "job_id": job_id,
                    "import_status": fields["import_status"],
                    "imported_path": fields.get("imported_path"),
                    "import_detail": fields.get("import_detail"),
                },
            )

    async def _finish(
        self,
        job_id: str,
        status: JobStatus,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        await self._update(
            job_id,
            {
                "status": status,
                "phase": None,
                "finished_at": utcnow(),
                "error_code": error_code,
                "error_message": error_message,
                # A finished job has no speed or ETA; leaving the last sample there
                # makes the queue look like it is still downloading.
                "speed_bps": None,
                "eta_s": None,
                **({"progress_pct": 100.0} if status is JobStatus.COMPLETED else {}),
            },
        )
        self.hub.publish(
            "job.state",
            {
                "job_id": job_id,
                "status": status,
                "phase": None,
                "error_message": error_message,
            },
        )
        await self._publish_summary(job_id)

    async def _cancelled(self, job_id: str, job_dir: Path) -> None:
        await asyncio.to_thread(shutil.rmtree, job_dir, True)
        await self._update(
            job_id,
            {
                "status": JobStatus.CANCELLED,
                "phase": None,
                "finished_at": utcnow(),
                "cancel_requested": False,
                "speed_bps": None,
                "eta_s": None,
            },
        )
        self.hub.publish(
            "job.state", {"job_id": job_id, "status": JobStatus.CANCELLED, "phase": None}
        )
        await self._publish_summary(job_id)

    async def _publish_summary(self, job_id: str) -> None:
        async with self.db.read_session() as session:
            request_id = await session.scalar(select(Job.request_id).where(Job.id == job_id))
            if request_id is None:  # pragma: no cover - deleted mid-run
                return
            rows = (
                await session.execute(
                    select(Job.status, func.count())
                    .where(Job.request_id == request_id)
                    .group_by(Job.status)
                )
            ).all()
        counts = {str(status): int(count) for status, count in rows}
        self.hub.publish(
            "request.summary",
            {
                "request_id": request_id,
                "total": sum(counts.values()),
                "completed": counts.get(JobStatus.COMPLETED, 0),
                "failed": counts.get(JobStatus.FAILED, 0),
            },
        )

    async def _flush_logs_forever(self, job_id: str, lines: deque[str]) -> None:
        while True:
            await asyncio.sleep(LOG_FLUSH_INTERVAL_S)
            await self._flush_logs(job_id, lines)

    async def _flush_logs(self, job_id: str, lines: deque[str]) -> None:
        if not lines:
            return
        pending = [lines.popleft() for _ in range(len(lines))]
        now = utcnow()
        async with self.db.write_session() as session:
            session.add_all(
                [JobLog(job_id=job_id, ts=now, level="info", line=line) for line in pending]
            )
        self.hub.publish("job.log", {"job_id": job_id, "lines": pending})

    # ---------------------------------------------------------------- recovery

    async def recover(self) -> None:
        """§6.1: finish cancelled jobs, then resume or fail whatever was running."""
        async with self.db.write_session() as session:
            jobs = list(await session.scalars(select(Job).where(Job.status.in_(ACTIVE_STATUSES))))
            cancelled_dirs = []
            for job in jobs:
                if job.cancel_requested:
                    job.status = JobStatus.CANCELLED
                    job.cancel_requested = False
                    job.finished_at = utcnow()
                    cancelled_dirs.append(Path(job.job_dir))
                elif self.settings.auto_resume:
                    job.status = JobStatus.QUEUED
                else:
                    job.status = JobStatus.FAILED
                    job.error_code = "interrupted"
                    job.error_message = "fetcharr restarted while this job was running"
                    job.finished_at = utcnow()
                job.phase = None
        for path in cancelled_dirs:
            await asyncio.to_thread(shutil.rmtree, path, True)


def _detect_tools() -> tuple[JsRuntime | None, bool]:
    return detect_js_runtime(), shutil.which("aria2c") is not None


def _progress_event(job_id: str, progress: Progress) -> dict[str, Any]:
    return {
        "job_id": job_id,
        "progress_pct": progress.pct,
        "downloaded_bytes": progress.downloaded_bytes,
        "total_bytes": progress.total_bytes,
        "speed_bps": progress.speed_bps,
        "eta_s": progress.eta_s,
    }
