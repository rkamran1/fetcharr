"""Turn an inspected URL plus options into a request and its queued jobs (§5, §6.1)."""

import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.config import Settings
from app.db.base import utcnow
from app.db.session import Database
from app.events.service import EventHub
from app.inspections.models import Inspection
from app.jobs.constants import ImportStatus, JobStatus
from app.jobs.manager import JobManager
from app.jobs.models import Job
from app.jobs.service import JobService
from app.library.naming import Other, build_path
from app.requests.exceptions import InspectionNotFound, RequestNotFound, UnnameableVideo
from app.requests.models import Request
from app.requests.schemas import (
    CreatedRequest,
    CreateRequest,
    PathPreview,
    PreviewRequest,
    RequestRead,
)
from app.ytdlp.schemas import DownloadOptions


class RequestService:
    def __init__(
        self,
        db: Database,
        settings: Settings,
        hub: EventHub,
        manager: JobManager,
        jobs: JobService,
    ) -> None:
        self.db = db
        self.settings = settings
        self.hub = hub
        self.manager = manager
        self.jobs = jobs

    async def create(self, body: CreateRequest) -> CreatedRequest:
        infos = [await self._inspection(item.inspection_id) for item in body.items]
        request_id = str(uuid.uuid4())
        now = utcnow()
        job_ids = [str(uuid.uuid4()) for _ in infos]

        async with self.db.write_session() as session:
            session.add(
                Request(
                    id=request_id,
                    media_type=body.media_type,
                    title=_title(infos[0]),
                    year=infos[0].get("release_year"),
                    options=body.options.model_dump(),
                    created_at=now,
                )
            )
            # No ORM relationship between the two, so the parent row is flushed first.
            await session.flush()
            for job_id, info in zip(job_ids, infos, strict=True):
                # Each job works in its own folder and moves out only when finished (§7.4).
                session.add(
                    Job(
                        id=job_id,
                        request_id=request_id,
                        url=str(info.get("webpage_url") or ""),
                        extractor=info.get("extractor"),
                        video_id=info.get("id"),
                        stream_type=info.get("stream_type"),
                        source_title=_title(info),
                        thumbnail_url=info.get("thumbnail"),
                        duration=info.get("duration"),
                        status=JobStatus.QUEUED,
                        step_timings={},
                        sidecar_paths=[],
                        import_status=ImportStatus.NOT_APPLICABLE,
                        max_attempts=body.options.retries + 1,
                        job_dir=str(self.settings.incomplete_dir / job_id),
                        created_at=now,
                    )
                )
        self.manager.wake()
        return CreatedRequest(id=request_id, jobs=job_ids)

    async def get(self, request_id: str) -> RequestRead:
        async with self.db.read_session() as session:
            request = await session.get(Request, request_id)
            if request is None:
                raise RequestNotFound(request_id)
            jobs = list(
                await session.scalars(
                    select(Job).where(Job.request_id == request_id).order_by(Job.created_at, Job.id)
                )
            )
        return RequestRead(
            id=request.id,
            media_type=request.media_type,
            title=request.title,
            created_at=request.created_at,
            jobs=[self.jobs.read(job) for job in jobs],
        )

    async def preview(self, body: PreviewRequest) -> PathPreview:
        info = await self._inspection(body.inspection_id)
        return PathPreview(path=str(self._path_for(info, body.options)))

    async def _inspection(self, inspection_id: int) -> dict[str, Any]:
        async with self.db.read_session() as session:
            row = await session.get(Inspection, inspection_id)
            if row is None:
                raise InspectionNotFound(inspection_id)
            return dict(row.info)

    def _path_for(self, info: dict[str, Any], options: DownloadOptions) -> Path:
        target = Other(title=_title(info), id=str(info.get("id") or ""))
        try:
            # `Other` has no quality token, so the preview is the real path (M3).
            relative = build_path(target, "", f".{options.container}")
        except ValueError as error:
            raise UnnameableVideo(str(error)) from error
        return self.settings.completed_dir / relative


def _title(info: dict[str, Any]) -> str:
    return str(info.get("title") or info.get("id") or "video")
