"""Turn an inspected URL plus options into a request and its queued jobs (§5, §6.1)."""

import asyncio
import uuid
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import ColumnElement, Select, column, func, or_, select, table, text

from app.config import Settings
from app.db.base import utcnow
from app.db.session import Database
from app.events.service import EventHub
from app.inspections.models import Inspection
from app.jobs.constants import ImportStatus, JobStatus
from app.jobs.manager import JobManager
from app.jobs.models import Job
from app.jobs.service import JobService
from app.library.naming import DailyEpisode, Episode, Movie, Other, Target, build_path
from app.requests.exceptions import InspectionNotFound, RequestNotFound, UnnameableVideo
from app.requests.models import Request
from app.requests.schemas import (
    CreatedRequest,
    CreateRequest,
    EpisodeRef,
    MediaDetails,
    MovieMedia,
    PathPreview,
    PreviewRequest,
    RequestFilters,
    RequestPage,
    RequestRead,
    TvMedia,
)
from app.requests.utils import estimated_quality, fts_match, search_words
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
        rows = [await self._inspection_row(item.inspection_id) for item in body.items]
        infos = [info for info, _site in rows]
        request_id = str(uuid.uuid4())
        now = utcnow()
        job_ids = [str(uuid.uuid4()) for _ in infos]
        media = body.media
        movie = media if isinstance(media, MovieMedia) else None
        series = media if isinstance(media, TvMedia) else None
        # A movie or an episode still has to be imported; `other` has nothing to (§6).
        import_status = (
            ImportStatus.NOT_APPLICABLE if body.media_type == "other" else ImportStatus.PENDING
        )

        async with self.db.write_session() as session:
            session.add(
                Request(
                    id=request_id,
                    media_type=body.media_type,
                    title=media.title if media else _title(infos[0]),
                    year=movie.year if movie else infos[0].get("release_year"),
                    numbering=series.numbering if series else None,
                    radarr_movie_id=movie.radarr_movie_id if movie else None,
                    sonarr_series_id=series.sonarr_series_id if series else None,
                    options=body.options.model_dump(),
                    created_at=now,
                )
            )
            # No ORM relationship between the two, so the parent row is flushed first.
            await session.flush()
            for job_id, (info, site_key), item in zip(job_ids, rows, body.items, strict=True):
                episode = item.episode or EpisodeRef()
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
                        site_key=site_key,
                        use_cookies=body.use_cookies,
                        season=episode.season,
                        episode=episode.number,
                        sonarr_episode_id=episode.sonarr_episode_id,
                        episode_title=episode.title or None,
                        air_date=episode.air_date,
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
        return self._read(request, jobs)

    async def history(self, filters: RequestFilters) -> RequestPage:
        """History: filtered, searched, newest first, one page at a time (§11, §12)."""
        count, page = history_queries(filters, self.db.reader.dialect.name)
        async with self.db.read_session() as session:
            total = await session.scalar(count)
            requests = list(await session.scalars(page))
            jobs = list(await session.scalars(jobs_of([request.id for request in requests])))
        by_request: dict[str, list[Job]] = {}
        for job in jobs:
            by_request.setdefault(job.request_id, []).append(job)
        return RequestPage(
            items=[self._read(request, by_request.get(request.id, [])) for request in requests],
            total=total or 0,
            page=filters.page,
            per_page=filters.per_page,
        )

    def _read(self, request: Request, jobs: list[Job]) -> RequestRead:
        return RequestRead(
            id=request.id,
            media_type=request.media_type,
            title=request.title,
            year=request.year,
            numbering=request.numbering,
            radarr_movie_id=request.radarr_movie_id,
            sonarr_series_id=request.sonarr_series_id,
            options=request.options,
            created_at=request.created_at,
            jobs=[self.jobs.read(job) for job in jobs],
        )

    async def preview(self, body: PreviewRequest) -> PathPreview:
        info = await self._inspection(body.inspection_id)
        path = self._path_for(info, body.options, body, body.episode)
        # A stat is blocking, and the answer decides whether the wizard has to ask (§3.2).
        exists = await asyncio.to_thread(path.is_file)
        return PathPreview(path=str(path), exists=exists)

    async def _inspection(self, inspection_id: int) -> dict[str, Any]:
        info, _site_key = await self._inspection_row(inspection_id)
        return info

    async def _inspection_row(self, inspection_id: int) -> tuple[dict[str, Any], str | None]:
        """The inspection's info, and the site whose cookies its URL uses (§8)."""
        async with self.db.read_session() as session:
            row = await session.get(Inspection, inspection_id)
            if row is None:
                raise InspectionNotFound(inspection_id)
            return dict(row.info), row.site_key

    def _path_for(
        self,
        info: dict[str, Any],
        options: DownloadOptions,
        details: MediaDetails,
        episode: EpisodeRef | None = None,
    ) -> Path:
        target = target_for(details, info, episode)
        try:
            # The real quality is only known after ffprobe, so the preview estimates it (§7.2).
            relative = build_path(target, estimated_quality(info, options), f".{options.container}")
        except ValueError as error:
            raise UnnameableVideo(str(error)) from error
        return self.settings.completed_dir / relative


#: The search index from revision 0009; SQLite only, so it isn't a model (§3.1).
JOBS_FTS = table("jobs_fts", column("request_id"))


def history_queries(filters: RequestFilters, dialect: str) -> tuple[Select[Any], Select[Any]]:
    """The count and the page of History's query, newest first with a stable order."""
    conditions = history_conditions(filters, dialect)
    count = select(func.count()).select_from(Request).where(*conditions)
    page = (
        select(Request)
        .where(*conditions)
        .order_by(Request.created_at.desc(), Request.id.desc())
        .limit(filters.per_page)
        .offset((filters.page - 1) * filters.per_page)
    )
    return count, page


def jobs_of(request_ids: list[str]) -> Select[tuple[Job]]:
    """The jobs of a page of requests, in the order they were created."""
    return select(Job).where(Job.request_id.in_(request_ids)).order_by(Job.created_at, Job.id)


def history_conditions(filters: RequestFilters, dialect: str) -> list[ColumnElement[bool]]:
    """The WHERE clause on `requests` for History's filters, ANDed (§11).

    Status, import status and site are about jobs, and must hold for the same job.
    """
    conditions: list[ColumnElement[bool]] = []
    if filters.type is not None:
        conditions.append(Request.media_type == filters.type)
    if filters.from_ is not None:
        conditions.append(Request.created_at >= _midnight(filters.from_))
    if filters.to is not None:
        conditions.append(Request.created_at < _midnight(filters.to + timedelta(days=1)))
    job_conditions = [
        condition
        for value, condition in (
            (filters.status, Job.status == filters.status),
            (filters.import_status, Job.import_status == filters.import_status),
            (filters.site, Job.site_key == filters.site),
        )
        if value is not None
    ]
    if job_conditions:
        # Not a correlated EXISTS: SQLite would then walk ix_jobs_status once per request.
        conditions.append(Request.id.in_(select(Job.request_id).where(*job_conditions)))
    search = search_request_ids(filters.q, dialect)
    if search is not None:
        conditions.append(Request.id.in_(search))
    return conditions


def search_request_ids(q: str | None, dialect: str) -> Select[tuple[str]] | None:
    """History search, the one repository function (§10): FTS5 on SQLite, else ILIKE."""
    return fts_request_ids(q) if dialect == "sqlite" else ilike_request_ids(q)


def fts_request_ids(q: str | None) -> Select[tuple[str]] | None:
    """Requests with a job whose request, source or episode title has every word's prefix."""
    match = fts_match(q)
    if match is None:
        return None
    matches = text("jobs_fts MATCH :match").bindparams(match=match)
    return select(JOBS_FTS.c.request_id).where(matches)


def ilike_request_ids(q: str | None) -> Select[tuple[str]] | None:
    """The Postgres fallback: every word inside one of the same three titles (§3.1)."""
    words = search_words(q)
    if not words:
        return None
    return (
        select(Job.request_id)
        .join(Request, Request.id == Job.request_id)
        .where(
            *(
                or_(
                    Request.title.icontains(word, autoescape=True),
                    Job.source_title.icontains(word, autoescape=True),
                    Job.episode_title.icontains(word, autoescape=True),
                )
                for word in words
            )
        )
    )


def _midnight(day: date) -> datetime:
    return datetime.combine(day, time())


def target_for(
    details: MediaDetails, info: dict[str, Any], episode: EpisodeRef | None = None
) -> Target:
    """The naming target: arr's own titles for a movie or an episode, the video's for other."""
    match details.media:
        case MovieMedia():
            return Movie(title=details.media.title, year=details.media.year)
        case TvMedia():
            return episode_target(details.media, episode or EpisodeRef())
        case _:
            return Other(title=_title(info), id=str(info.get("id") or ""))


def episode_target(series: TvMedia, episode: EpisodeRef) -> Target:
    """Sonarr's series and episode titles, numbered the way Sonarr numbers them (§7.2)."""
    if series.numbering == "daily":
        if episode.air_date is None:
            raise UnnameableVideo("a daily episode needs an air date")
        return DailyEpisode(
            series_title=series.title,
            air_date=episode.air_date,
            episode_title=episode.title,
            season=episode.season,
        )
    if episode.number is None:
        raise UnnameableVideo("a standard episode needs an episode number")
    return Episode(
        series_title=series.title,
        season=episode.season or 0,
        episode=episode.number,
        episode_title=episode.title,
    )


def _title(info: dict[str, Any]) -> str:
    return str(info.get("title") or info.get("id") or "video")
