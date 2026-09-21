"""Inspect a URL (requirements §5 step 1): cache lookup → `yt-dlp -J` → store."""

import asyncio
import shutil
import tempfile
from datetime import timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select

from app.db.base import utcnow
from app.db.session import Database
from app.inspections.exceptions import InspectError
from app.inspections.models import Inspection
from app.inspections.schemas import InspectResult, PreviousDownload
from app.inspections.utils import normalise
from app.jobs.constants import ImportStatus, JobStatus
from app.jobs.models import Job
from app.sites.service import SiteCookiesInUse, SitesService
from app.ytdlp.cookies import write_private
from app.ytdlp.inspect import ErrorKind, YtdlpError, build_inspect_argv, is_auth_error, run_json
from app.ytdlp.runtime import JsRuntime, detect_js_runtime

CACHE_TTL = timedelta(minutes=30)

_STATUS: dict[ErrorKind, int] = {
    "needs_cookies": 422,
    "unsupported": 422,
    "unavailable": 422,
    "timeout": 504,
    "failed": 502,
}


def _inspect_tools() -> tuple[JsRuntime | None, bool]:
    return detect_js_runtime(), shutil.which("aria2c") is not None


class InspectionService:
    def __init__(self, db: Database, sites: SitesService) -> None:
        self.db = db
        self.sites = sites

    async def inspect(self, url: str) -> InspectResult:
        """The normalised info for one URL, cached for 30 minutes; raises InspectError."""
        async with self.db.read_session() as session:
            cached = await session.scalar(
                select(Inspection)
                .where(Inspection.url == url, Inspection.expires_at > utcnow())
                .order_by(Inspection.created_at.desc())
                .limit(1)
            )
        if cached is not None:
            # Never cached: a download may have finished since the inspection was.
            return InspectResult(
                inspection_id=cached.id,
                site_key=cached.site_key,
                previous_downloads=await self.previous_downloads(cached.info),
                **cached.info,
            )

        # No session is open while yt-dlp runs (requirements §3.1).
        site_key = await self.sites.site_key_for(url)
        cookies = await self.sites.cookies_for_site(site_key) if site_key else None
        js_runtime, aria2c_available = await asyncio.to_thread(_inspect_tools)
        try:
            raw = await _run_with_cookies(url, js_runtime, cookies)
        except YtdlpError as error:
            if cookies is not None and is_auth_error(error.kind, error.message):
                await self.sites.flag(cookies.site_key)
            raise InspectError(
                _STATUS[error.kind],
                error.message,
                needs_cookies=error.kind == "needs_cookies",
                site_key=site_key,
            ) from error
        if cookies is not None:
            await self.sites.used(cookies.site_key)
        info = await asyncio.to_thread(normalise, raw, aria2c_available)
        now = utcnow()
        async with self.db.write_session() as session:
            await session.execute(delete(Inspection).where(Inspection.expires_at <= now))
            row = Inspection(
                url=url, site_key=site_key, info=info, created_at=now, expires_at=now + CACHE_TTL
            )
            session.add(row)
            await session.flush()
            inspection_id = row.id
        return InspectResult(
            inspection_id=inspection_id,
            site_key=site_key,
            previous_downloads=await self.previous_downloads(info),
            **info,
        )

    async def previous_downloads(self, info: dict[str, Any]) -> list[PreviousDownload]:
        """Finished jobs with this video's extractor and id, newest first (§10)."""
        video_id = info.get("id")
        if not video_id:
            return []
        async with self.db.read_session() as session:
            jobs = list(
                await session.scalars(
                    select(Job)
                    .where(
                        Job.video_id == video_id,
                        Job.extractor == info.get("extractor"),
                        Job.status == JobStatus.COMPLETED,
                    )
                    .order_by(Job.created_at.desc(), Job.id)
                )
            )
        return [
            PreviousDownload(
                job_id=job.id,
                created_at=job.created_at,
                media_type=job.request.media_type,
                path=job.imported_path
                if job.import_status == ImportStatus.IMPORTED
                else job.completed_path,
                import_status=job.import_status,
            )
            for job in jobs
        ]


async def _run_with_cookies(
    url: str, js_runtime: JsRuntime | None, cookies: SiteCookiesInUse | None
) -> Any:
    """`yt-dlp -J`, with the site's cookies in a private temp dir that never outlives it (§8)."""
    if cookies is None:
        return await run_json(build_inspect_argv(url, js_runtime))
    path = await asyncio.to_thread(_write_temp_cookies, cookies.text)
    try:
        return await run_json(build_inspect_argv(url, js_runtime, path))
    finally:
        await asyncio.to_thread(shutil.rmtree, path.parent, True)


def _write_temp_cookies(text: str) -> Path:
    """`cookies.txt` (0600) in a fresh 0700 temp dir; the caller removes the dir."""
    path = Path(tempfile.mkdtemp(prefix="fetcharr-inspect-")) / "cookies.txt"
    write_private(path, text)
    return path
