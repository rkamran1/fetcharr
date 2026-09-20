"""Turn an inspected URL plus options into a request and its queued jobs (§5, §6.1)."""

import asyncio
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
from app.library.naming import Movie, Other, Target, build_path
from app.requests.exceptions import InspectionNotFound, RequestNotFound, UnnameableVideo
from app.requests.models import Request
from app.requests.schemas import (
    CreatedRequest,
    CreateRequest,
    MediaDetails,
    PathPreview,
    PreviewRequest,
    RequestRead,
)
from app.requests.utils import estimated_quality
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
        movie = body.media
        # A movie job still has to be imported; `other` has nothing to import (§6).
        import_status = (
            ImportStatus.PENDING if body.media_type == "movie" else ImportStatus.NOT_APPLICABLE
        )

        async with self.db.write_session() as session:
            session.add(
                Request(
                    id=request_id,
                    media_type=body.media_type,
                    title=movie.title if movie else _title(infos[0]),
                    year=movie.year if movie else infos[0].get("release_year"),
                    radarr_movie_id=movie.radarr_movie_id if movie else None,
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
                        collision_policy=body.collision_policy,
                        import_status=import_status,
                        import_attempts=0,
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
        path = self._path_for(info, body.options, body)
        # A stat is blocking, and the answer decides whether the wizard has to ask (§3.2).
        exists = await asyncio.to_thread(path.is_file)
        return PathPreview(path=str(path), exists=exists)

    async def _inspection(self, inspection_id: int) -> dict[str, Any]:
        async with self.db.read_session() as session:
            row = await session.get(Inspection, inspection_id)
            if row is None:
                raise InspectionNotFound(inspection_id)
            return dict(row.info)

    def _path_for(
        self, info: dict[str, Any], options: DownloadOptions, details: MediaDetails
    ) -> Path:
        target = target_for(details, info)
        try:
            # The real quality is only known after ffprobe, so the preview estimates it (§7.2).
            relative = build_path(target, estimated_quality(info, options), f".{options.container}")
        except ValueError as error:
            raise UnnameableVideo(str(error)) from error
        return self.settings.completed_dir / relative


def target_for(details: MediaDetails, info: dict[str, Any]) -> Target:
    """The naming target: Radarr's own title and year for a movie, the video's own for other."""
    if details.media is not None:
        return Movie(title=details.media.title, year=details.media.year)
    return Other(title=_title(info), id=str(info.get("id") or ""))


def _title(info: dict[str, Any]) -> str:
    return str(info.get("title") or info.get("id") or "video")
