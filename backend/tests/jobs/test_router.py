"""Every job endpoint's success path; the 401s come from tests/repo/test_route_protection.py."""

import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.config import Settings
from app.db.base import utcnow
from app.db.session import Database
from app.jobs.constants import ImportStatus, JobStatus
from app.jobs.models import Job, JobLog
from app.requests.models import Request
from tests.conftest import exists, is_file, make_client, setup_account
from tests.fake_ytdlp import FakeYtdlp


@pytest.fixture
async def signed_in(app: FastAPI) -> Any:
    async with make_client(app) as client:
        await setup_account(client)
        yield client


@pytest.fixture
def add_job(app: FastAPI, settings: Settings) -> Callable[..., Any]:
    """Insert one job directly; `POST /api/requests` is covered in tests/requests."""

    async def insert(**fields: Any) -> str:
        db: Database = app.state.db
        job_id = str(uuid.uuid4())
        request_id = str(uuid.uuid4())
        async with db.write_session() as session:
            session.add(
                Request(
                    id=request_id,
                    media_type="other",
                    title="Big Buck Bunny",
                    options={"quality": "best"},
                    created_at=utcnow(),
                )
            )
            await session.flush()
            session.add(
                Job(
                    id=job_id,
                    request_id=request_id,
                    url="https://example.com/v",
                    video_id="abc123",
                    source_title="Big Buck Bunny",
                    status=fields.pop("status", JobStatus.QUEUED),
                    step_timings={},
                    sidecar_paths=[],
                    job_dir=str(settings.incomplete_dir / job_id),
                    created_at=utcnow(),
                    **fields,
                )
            )
        return job_id

    return insert


async def test_get_job(signed_in: httpx.AsyncClient, add_job: Callable[..., Any]) -> None:
    job_id = await add_job()

    response = await signed_in.get(f"/api/jobs/{job_id}")

    assert response.status_code == 200
    assert response.json()["id"] == job_id
    assert response.json()["status"] == "queued"
    assert (await signed_in.get("/api/jobs/nope")).status_code == 404


async def test_list_jobs(signed_in: httpx.AsyncClient, add_job: Callable[..., Any]) -> None:
    first = await add_job()
    second = await add_job()

    response = await signed_in.get("/api/jobs")

    assert response.status_code == 200
    assert {job["id"] for job in response.json()["jobs"]} == {first, second}


async def test_get_job_log(
    signed_in: httpx.AsyncClient, app: FastAPI, add_job: Callable[..., Any]
) -> None:
    job_id = await add_job()
    db: Database = app.state.db
    async with db.write_session() as session:
        session.add_all(
            [
                JobLog(job_id=job_id, ts=utcnow(), level="info", line="first"),
                JobLog(job_id=job_id, ts=utcnow(), level="info", line="second"),
            ]
        )

    response = await signed_in.get(f"/api/jobs/{job_id}/log")

    assert response.status_code == 200
    assert [line["line"] for line in response.json()["lines"]] == ["first", "second"]
    assert (await signed_in.get("/api/jobs/nope/log")).status_code == 404


async def test_cancel_queued_job(
    signed_in: httpx.AsyncClient, settings: Settings, add_job: Callable[..., Any]
) -> None:
    job_id = await add_job()
    job_dir = settings.incomplete_dir / job_id
    job_dir.mkdir(parents=True)

    response = await signed_in.post(f"/api/jobs/{job_id}/cancel")

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert not exists(job_dir)


async def test_cancel_after_organize_started_returns_409(
    signed_in: httpx.AsyncClient, app: FastAPI, add_job: Callable[..., Any]
) -> None:
    """Cancel is only possible before the organize step starts (§6.1)."""
    job_id = await add_job(status=JobStatus.ORGANIZING)

    response = await signed_in.post(f"/api/jobs/{job_id}/cancel")

    assert response.status_code == 409
    db: Database = app.state.db
    async with db.read_session() as session:
        job = await session.get(Job, job_id)
        assert job is not None
        assert job.cancel_requested is False
        assert job.status == JobStatus.ORGANIZING


async def test_retry_failed_job(
    signed_in: httpx.AsyncClient, add_job: Callable[..., Any], fake_ytdlp: FakeYtdlp
) -> None:
    fake_ytdlp.downloads(exit_code=1, stderr="ERROR: unable to download video data")
    job_id = await add_job(status=JobStatus.FAILED, error_code="YtDlpFailed", error_message="boom")

    response = await signed_in.post(f"/api/jobs/{job_id}/retry")

    assert response.status_code == 200
    assert response.json()["status"] == "queued"
    assert response.json()["error_message"] is None


async def test_retry_rejects_a_running_job(
    signed_in: httpx.AsyncClient, add_job: Callable[..., Any]
) -> None:
    job_id = await add_job(status=JobStatus.DOWNLOADING)

    response = await signed_in.post(f"/api/jobs/{job_id}/retry")

    assert response.status_code == 409


async def test_delete_job(
    signed_in: httpx.AsyncClient, app: FastAPI, add_job: Callable[..., Any]
) -> None:
    job_id = await add_job(status=JobStatus.COMPLETED)

    response = await signed_in.delete(f"/api/jobs/{job_id}")

    assert response.status_code == 204
    assert (await signed_in.get(f"/api/jobs/{job_id}")).status_code == 404


async def test_delete_job_with_file(
    signed_in: httpx.AsyncClient, settings: Settings, add_job: Callable[..., Any]
) -> None:
    completed = settings.completed_dir / "other" / "Big Buck Bunny [abc123].mkv"
    completed.parent.mkdir(parents=True, exist_ok=True)
    completed.write_bytes(b"video")
    job_id = await add_job(status=JobStatus.COMPLETED, completed_path=str(completed))
    job_dir = settings.incomplete_dir / job_id
    job_dir.mkdir(parents=True)

    response = await signed_in.delete(f"/api/jobs/{job_id}?delete_file=true")

    assert response.status_code == 204
    assert not exists(completed)
    assert not exists(job_dir)


async def test_delete_refuses_a_path_outside_the_roots(
    signed_in: httpx.AsyncClient, tmp_path: Path, add_job: Callable[..., Any]
) -> None:
    outside = tmp_path / "somewhere-else.mkv"
    outside.write_bytes(b"precious")
    job_id = await add_job(status=JobStatus.COMPLETED, completed_path=str(outside))

    response = await signed_in.delete(f"/api/jobs/{job_id}?delete_file=true")

    assert response.status_code == 400
    assert is_file(outside)
    assert (await signed_in.get(f"/api/jobs/{job_id}")).status_code == 200


# ------------------------------------------------ AC8: POST /api/jobs/{id}/import


async def test_retry_import_requeues_a_rejected_job(
    signed_in: httpx.AsyncClient, app: FastAPI, add_job: Callable[..., Any]
) -> None:
    job_id = await add_job(
        status=JobStatus.COMPLETED,
        last_completed_step="import",
        import_status=ImportStatus.NOT_IMPORTED,
        import_detail={"rejections": ["Unknown movie"]},
    )

    response = await signed_in.post(f"/api/jobs/{job_id}/import")

    assert response.status_code == 200
    body = response.json()
    assert body["import_status"] == ImportStatus.PENDING
    assert body["import_detail"] is None
    assert body["status"] == JobStatus.QUEUED
    # It resumes at the import step, so the file is never downloaded or moved again (§6.1).
    async with app.state.db.read_session() as session:
        job = await session.get(Job, job_id)
        assert job is not None and job.last_completed_step == "organize"


async def test_retry_import_rejects_an_already_imported_job(
    signed_in: httpx.AsyncClient, add_job: Callable[..., Any]
) -> None:
    job_id = await add_job(status=JobStatus.COMPLETED, import_status=ImportStatus.IMPORTED)

    response = await signed_in.post(f"/api/jobs/{job_id}/import")

    assert response.status_code == 409
    assert "imported" in response.json()["detail"]


async def test_retry_import_rejects_an_unknown_job(signed_in: httpx.AsyncClient) -> None:
    assert (await signed_in.post("/api/jobs/nope/import")).status_code == 404
