"""Inspect a URL (requirements §5 step 1): cache lookup → `yt-dlp -J` → store."""

import asyncio
import shutil
from datetime import timedelta

from sqlalchemy import delete, select

from app.db.base import utcnow
from app.db.session import Database
from app.inspections.exceptions import InspectError
from app.inspections.models import Inspection
from app.inspections.schemas import InspectResult
from app.inspections.utils import normalise
from app.ytdlp.inspect import ErrorKind, YtdlpError, build_inspect_argv, run_json
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
    def __init__(self, db: Database) -> None:
        self.db = db

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
            return InspectResult(inspection_id=cached.id, **cached.info)

        # No session is open while yt-dlp runs (requirements §3.1).
        js_runtime, aria2c_available = await asyncio.to_thread(_inspect_tools)
        try:
            raw = await run_json(build_inspect_argv(url, js_runtime))
        except YtdlpError as error:
            raise InspectError(
                _STATUS[error.kind],
                error.message,
                needs_cookies=error.kind == "needs_cookies",
            ) from error
        info = await asyncio.to_thread(normalise, raw, aria2c_available)

        now = utcnow()
        async with self.db.write_session() as session:
            await session.execute(delete(Inspection).where(Inspection.expires_at <= now))
            row = Inspection(url=url, info=info, created_at=now, expires_at=now + CACHE_TTL)
            session.add(row)
            await session.flush()
            inspection_id = row.id
        return InspectResult(inspection_id=inspection_id, **info)
