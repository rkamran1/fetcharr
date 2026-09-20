"""`POST /api/requests`, `GET /api/requests/{id}` and `POST /api/preview` (requirements §11)."""

from collections.abc import Callable
from datetime import timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.config import Settings
from app.db.base import utcnow
from app.db.session import Database
from app.inspections.models import Inspection
from tests.conftest import make_client, setup_account
from tests.fake_ytdlp import FakeYtdlp

INFO = {
    "title": "Big Buck Bunny",
    "uploader": "Blender",
    "thumbnail": "https://example.com/thumb.jpg",
    "duration": 635.0,
    "webpage_url": "https://example.com/watch?v=abc123",
    "extractor": "generic",
    "id": "abc123",
    "upload_date": "20141110",
    "release_year": 2014,
    "video_heights": [1080, 720],
    "video_codecs": ["avc1"],
    "audio_tracks": [],
    "has_hdr": False,
    "subtitles": {},
    "automatic_captions": {},
    "estimated_sizes": {},
    "stream_type": "http",
    "auto": {"fragments": 1, "use_aria2c": False},
}

OPTIONS = {
    "quality": "1080p",
    "container": "mkv",
    "fragments": "auto",
    "use_aria2c": "auto",
    "retries": 5,
}


@pytest.fixture
async def signed_in(app: FastAPI, fake_ytdlp: FakeYtdlp) -> Any:
    """The stub is on PATH so a created request can never reach the real internet (§16)."""
    fake_ytdlp.downloads(exit_code=1, stderr="ERROR: unable to download video data")
    async with make_client(app) as client:
        await setup_account(client)
        yield client


@pytest.fixture
def add_inspection(app: FastAPI) -> Callable[..., Any]:
    async def insert(**overrides: Any) -> int:
        db: Database = app.state.db
        now = utcnow()
        async with db.write_session() as session:
            row = Inspection(
                url=str(INFO["webpage_url"]),
                info={**INFO, **overrides},
                created_at=now,
                expires_at=now + timedelta(minutes=30),
            )
            session.add(row)
            await session.flush()
            return row.id

    return insert


async def test_creates_a_request_and_a_queued_job(
    signed_in: httpx.AsyncClient, settings: Settings, add_inspection: Callable[..., Any]
) -> None:
    inspection_id = await add_inspection()

    response = await signed_in.post(
        "/api/requests",
        json={
            "media_type": "other",
            "items": [{"inspection_id": inspection_id}],
            "options": OPTIONS,
        },
    )

    assert response.status_code == 201
    body = response.json()
    job = (await signed_in.get(f"/api/jobs/{body['jobs'][0]}")).json()
    assert job["request_id"] == body["id"]
    assert job["source_title"] == "Big Buck Bunny"
    assert job["url"] == INFO["webpage_url"]
    assert job["import_status"] == "n/a"
    assert job["status"] in ("queued", "starting", "downloading", "failed")

    detail = await signed_in.get(f"/api/requests/{body['id']}")
    assert detail.status_code == 200
    assert detail.json()["media_type"] == "other"
    assert [j["id"] for j in detail.json()["jobs"]] == body["jobs"]
    assert detail.json()["jobs"][0]["url"] == INFO["webpage_url"]
    # The work folder is the job's own, under INCOMPLETE_DIR (§7.4).
    assert str(settings.incomplete_dir) in str(settings.incomplete_dir / body["jobs"][0])


async def test_rejects_an_unknown_inspection(signed_in: httpx.AsyncClient) -> None:
    response = await signed_in.post(
        "/api/requests",
        json={"media_type": "other", "items": [{"inspection_id": 999}], "options": OPTIONS},
    )

    assert response.status_code == 404


async def test_rejects_an_unknown_request(signed_in: httpx.AsyncClient) -> None:
    assert (await signed_in.get("/api/requests/nope")).status_code == 404


async def test_rejects_options_outside_the_allow_list(
    signed_in: httpx.AsyncClient, add_inspection: Callable[..., Any]
) -> None:
    inspection_id = await add_inspection()

    response = await signed_in.post(
        "/api/requests",
        json={
            "media_type": "other",
            "items": [{"inspection_id": inspection_id}],
            "options": {**OPTIONS, "exec": "rm -rf /"},
        },
    )

    assert response.status_code == 422


async def test_preview_returns_the_completed_path(
    signed_in: httpx.AsyncClient, settings: Settings, add_inspection: Callable[..., Any]
) -> None:
    inspection_id = await add_inspection()

    response = await signed_in.post(
        "/api/preview",
        json={"media_type": "other", "inspection_id": inspection_id, "options": OPTIONS},
    )

    assert response.status_code == 200
    assert response.json()["path"] == str(
        settings.completed_dir / "other" / "Big Buck Bunny [abc123].mkv"
    )


async def test_preview_follows_the_container(
    signed_in: httpx.AsyncClient, settings: Settings, add_inspection: Callable[..., Any]
) -> None:
    inspection_id = await add_inspection(title="Some: Video")

    response = await signed_in.post(
        "/api/preview",
        json={
            "media_type": "other",
            "inspection_id": inspection_id,
            "options": {**OPTIONS, "container": "mp4"},
        },
    )

    assert response.json()["path"] == str(
        settings.completed_dir / "other" / "Some - Video [abc123].mp4"
    )
