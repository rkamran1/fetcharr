"""Inspect endpoint (requirements §5 step 1, §11)."""

import asyncio
import shutil
from datetime import timedelta
from typing import Annotated, Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import AfterValidator, BaseModel, StringConstraints
from sqlalchemy import delete, select

from app.db.models import Inspection, utcnow
from app.ytdlp.inspect import InspectError, run_inspect
from app.ytdlp.runtime import JsRuntime, detect_js_runtime

CACHE_TTL = timedelta(minutes=30)

router = APIRouter(prefix="/api")


def _check_url(url: str) -> str:
    if url.startswith("-"):
        raise ValueError("URL must not start with '-'")
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("Only http and https URLs are supported")
    return url


class InspectRequest(BaseModel):
    url: Annotated[str, StringConstraints(strip_whitespace=True), AfterValidator(_check_url)]


class AudioTrack(BaseModel):
    lang: str | None
    codec: str
    abr: int | None


class AutoSettings(BaseModel):
    fragments: int
    use_aria2c: bool


class InspectResult(BaseModel):
    inspection_id: int
    title: str | None
    uploader: str | None
    thumbnail: str | None
    duration: float | None
    webpage_url: str | None
    extractor: str | None
    id: str | None
    upload_date: str | None
    release_year: int | None
    video_heights: list[int]
    video_codecs: list[str]
    audio_tracks: list[AudioTrack]
    has_hdr: bool
    subtitles: dict[str, list[str]]
    automatic_captions: dict[str, list[str]]
    estimated_sizes: dict[str, int]
    stream_type: Literal["hls", "dash", "http"]
    auto: AutoSettings


def _inspect_tools() -> tuple[JsRuntime | None, bool]:
    return detect_js_runtime(), shutil.which("aria2c") is not None


@router.post("/inspect", response_model=InspectResult)
async def inspect(body: InspectRequest, request: Request) -> InspectResult | JSONResponse:
    db = request.app.state.db
    async with db.read_session() as session:
        cached = await session.scalar(
            select(Inspection)
            .where(Inspection.url == body.url, Inspection.expires_at > utcnow())
            .order_by(Inspection.created_at.desc())
            .limit(1)
        )
    if cached is not None:
        return InspectResult(inspection_id=cached.id, **cached.info)

    # No session is open while yt-dlp runs (requirements §3.1).
    js_runtime, aria2c_available = await asyncio.to_thread(_inspect_tools)
    try:
        info = await run_inspect(body.url, js_runtime, aria2c_available)
    except InspectError as error:
        return JSONResponse(
            status_code=error.status,
            content={"detail": error.detail, "needs_cookies": error.needs_cookies},
        )

    now = utcnow()
    async with db.write_session() as session:
        await session.execute(delete(Inspection).where(Inspection.expires_at <= now))
        row = Inspection(url=body.url, info=info, created_at=now, expires_at=now + CACHE_TTL)
        session.add(row)
        await session.flush()
        inspection_id = row.id
    return InspectResult(inspection_id=inspection_id, **info)
