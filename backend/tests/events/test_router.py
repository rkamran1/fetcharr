"""The SSE stream (requirements §6, §11): live progress and state for a running job.

`httpx.ASGITransport` buffers a response until it completes, so an endless SSE body can't be
read through it. The job's events are therefore asserted on a real `EventHub` subscription
(what the endpoint serves), and the wire format on the endpoint's own generator.
"""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from app.config import Settings
from app.db.base import utcnow
from app.db.session import Database
from app.events import router as events_router
from app.events.schemas import Event
from app.events.service import EventHub
from app.jobs.constants import JobStatus
from app.jobs.models import Job
from app.requests.models import Request
from tests.conftest import make_client, setup_account
from tests.fake_ytdlp import FakeYtdlp

_LIFECYCLE = (
    JobStatus.STARTING,
    JobStatus.DOWNLOADING,
    JobStatus.POSTPROCESSING,
    JobStatus.ORGANIZING,
    JobStatus.COMPLETED,
)


@pytest.fixture
async def signed_in(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with make_client(app) as client:
        await setup_account(client)
        yield client


async def test_events_requires_auth(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/events")).status_code == 401


async def test_events_stream_progress_and_state_for_a_job(
    app: FastAPI,
    settings: Settings,
    fake_ytdlp: FakeYtdlp,
    media: dict[str, Path],
) -> None:
    fake_ytdlp.downloads(media["small"], progress_lines=6, delay=0.05)
    hub: EventHub = app.state.hub
    collected: list[Event] = []

    async with hub.subscribe() as queue:
        job_id = await _queue_job(app, settings)
        app.state.manager.wake()
        async with asyncio.timeout(30):
            while True:
                event = await queue.get()
                collected.append(event)
                if event.type == "job.state" and event.data["status"] == JobStatus.COMPLETED:
                    break

    progress = [event.data for event in collected if event.type == "job.progress"]
    states = [event.data["status"] for event in collected if event.type == "job.state"]

    assert all(data["job_id"] == job_id for data in progress)
    downloaded = [data["downloaded_bytes"] for data in progress if data["downloaded_bytes"]]
    assert len(downloaded) >= 2
    assert downloaded == sorted(downloaded)
    assert downloaded[-1] > downloaded[0]
    # The §6 lifecycle, in order and ending completed.
    assert states == [status for status in states if status in _LIFECYCLE]
    assert states.index(JobStatus.DOWNLOADING) < states.index(JobStatus.ORGANIZING)
    assert JobStatus.POSTPROCESSING in states
    assert states[-1] == JobStatus.COMPLETED


async def test_events_endpoint_frames_events_as_sse(
    signed_in: httpx.AsyncClient, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(events_router, "KEEPALIVE_S", 0.05)
    hub: EventHub = app.state.hub
    response = await events_router.events(hub)
    body = response.body_iterator

    assert response.media_type == "text/event-stream"
    assert response.headers["cache-control"] == "no-cache"
    assert await anext(body) == ": connected\n\n"

    hub.publish("job.progress", {"job_id": "j1", "downloaded_bytes": 10, "progress_pct": 5.0})
    chunk = await anext(body)
    name, data = chunk.split("\n")[0], json.loads(chunk.split("\n")[1].removeprefix("data: "))
    assert name == "event: job.progress"
    assert data == {"job_id": "j1", "downloaded_bytes": 10, "progress_pct": 5.0}
    assert chunk.endswith("\n\n")

    # Nothing to send: the stream stays alive with a comment line.
    assert await anext(body) == ": keep-alive\n\n"
    await body.aclose()


async def test_hub_publishes_only_to_current_subscribers(app: FastAPI) -> None:
    hub: EventHub = app.state.hub
    async with hub.subscribe() as queue:
        hub.publish("job.log", {"job_id": "x", "lines": ["hello"]})
        assert (await asyncio.wait_for(queue.get(), 1)).data["lines"] == ["hello"]
    hub.publish("job.log", {"job_id": "x", "lines": ["after"]})

    assert queue.empty()


def test_snapshot_is_dropped_when_the_job_ends(app: FastAPI) -> None:
    hub: EventHub = app.state.hub
    hub.publish("job.progress", {"job_id": "x", "downloaded_bytes": 5, "progress_pct": 1.0})

    assert hub.snapshot("x") is not None
    hub.forget("x")
    assert hub.snapshot("x") is None


async def _queue_job(app: FastAPI, settings: Settings) -> str:
    db: Database = app.state.db
    job_id = str(uuid.uuid4())
    request_id = str(uuid.uuid4())
    async with db.write_session() as session:
        session.add(
            Request(
                id=request_id,
                media_type="other",
                title="Big Buck Bunny",
                options={"quality": "best", "retries": 0},
                created_at=utcnow(),
            )
        )
        await session.flush()
        session.add(
            Job(
                id=job_id,
                request_id=request_id,
                url="https://example.com/watch?v=abc123",
                video_id="abc123",
                stream_type="http",
                source_title="Big Buck Bunny",
                status=JobStatus.QUEUED,
                step_timings={},
                sidecar_paths=[],
                job_dir=str(settings.incomplete_dir / job_id),
                created_at=utcnow(),
            )
        )
    return job_id
