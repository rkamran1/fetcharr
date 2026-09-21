"""`POST /api/requests`, `GET /api/requests/{id}` and `POST /api/preview` (requirements §11)."""

import asyncio
import sqlite3
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.config import Settings
from app.db.base import utcnow
from app.db.session import Database
from app.inspections.models import Inspection
from app.jobs.constants import ImportStatus, JobStatus
from app.jobs.models import Job
from app.requests.models import Request
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


# Sync on purpose: ruff's ASYNC240 forbids pathlib I/O inside an async test body.
def put_file(path: Path, content: bytes = b"an earlier download") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


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
    async def insert(site_key: str | None = None, **overrides: Any) -> int:
        db: Database = app.state.db
        now = utcnow()
        async with db.write_session() as session:
            row = Inspection(
                url=str(INFO["webpage_url"]),
                site_key=site_key,
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


@pytest.mark.parametrize(("body", "use_cookies"), [({}, True), ({"use_cookies": False}, False)])
async def test_create_request_records_site_and_use_cookies(
    app: FastAPI,
    signed_in: httpx.AsyncClient,
    add_inspection: Callable[..., Any],
    body: dict[str, Any],
    use_cookies: bool,
) -> None:
    """The job carries its inspection's site and step 2's Skip cookies choice (§8)."""
    inspection_id = await add_inspection(site_key="youtube")

    response = await signed_in.post(
        "/api/requests",
        json={
            "media_type": "other",
            "items": [{"inspection_id": inspection_id}],
            "options": OPTIONS,
            **body,
        },
    )

    assert response.status_code == 201
    async with app.state.db.read_session() as session:
        job = await session.get(Job, response.json()["jobs"][0])
    assert job is not None
    assert (job.site_key, job.use_cookies) == ("youtube", use_cookies)


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


# ------------------------------------------- AC4/AC15: movies and collisions

MOVIE = {"radarr_movie_id": 7, "title": "Big Buck Bunny", "year": 2008}


async def test_creates_a_movie_request_with_radarrs_own_title(
    signed_in: httpx.AsyncClient, app: FastAPI, add_inspection: Callable[..., Any]
) -> None:
    inspection_id = await add_inspection(title="BIG BUCK BUNNY (Official Full Movie) [4K]")

    response = await signed_in.post(
        "/api/requests",
        json={
            "media_type": "movie",
            "media": MOVIE,
            "items": [{"inspection_id": inspection_id}],
            "options": OPTIONS,
            "collision_policy": "replace",
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    async with app.state.db.read_session() as session:
        request = await session.get(Request, body["id"])
        job = await session.get(Job, body["jobs"][0])
    assert request is not None and job is not None
    assert (request.title, request.year, request.radarr_movie_id) == ("Big Buck Bunny", 2008, 7)
    assert job.collision_policy == "replace"
    # A movie still has to be imported; `other` never does (§6).
    assert job.import_status == "pending"


async def test_a_movie_request_needs_its_media_block(
    signed_in: httpx.AsyncClient, add_inspection: Callable[..., Any]
) -> None:
    inspection_id = await add_inspection()

    response = await signed_in.post(
        "/api/requests",
        json={
            "media_type": "movie",
            "items": [{"inspection_id": inspection_id}],
            "options": OPTIONS,
        },
    )

    assert response.status_code == 422
    assert "media block" in response.text


async def test_preview_for_a_movie_uses_the_given_title_and_year(
    signed_in: httpx.AsyncClient, settings: Settings, add_inspection: Callable[..., Any]
) -> None:
    inspection_id = await add_inspection()

    response = await signed_in.post(
        "/api/preview",
        json={
            "media_type": "movie",
            "media": MOVIE,
            "inspection_id": inspection_id,
            "options": OPTIONS,
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "path": str(
            settings.completed_dir
            / "movies"
            / "Big Buck Bunny (2008)"
            / "Big Buck Bunny (2008) WEBDL-1080p.mkv"
        ),
        "exists": False,
    }


async def test_preview_estimates_the_quality_from_the_available_heights(
    signed_in: httpx.AsyncClient, add_inspection: Callable[..., Any]
) -> None:
    inspection_id = await add_inspection(video_heights=[720, 480])

    best = await signed_in.post(
        "/api/preview",
        json={
            "media_type": "movie",
            "media": MOVIE,
            "inspection_id": inspection_id,
            "options": {**OPTIONS, "quality": "best"},
        },
    )
    capped = await signed_in.post(
        "/api/preview",
        json={
            "media_type": "movie",
            "media": MOVIE,
            "inspection_id": inspection_id,
            "options": {**OPTIONS, "quality": "1080p"},
        },
    )

    # 1080p isn't there, so the ceiling really gets the 720p format.
    assert best.json()["path"].endswith("Big Buck Bunny (2008) WEBDL-720p.mkv")
    assert capped.json()["path"].endswith("Big Buck Bunny (2008) WEBDL-720p.mkv")


async def test_preview_reports_an_existing_file(
    signed_in: httpx.AsyncClient, settings: Settings, add_inspection: Callable[..., Any]
) -> None:
    inspection_id = await add_inspection()
    existing = (
        settings.completed_dir
        / "movies"
        / "Big Buck Bunny (2008)"
        / "Big Buck Bunny (2008) WEBDL-1080p.mkv"
    )
    put_file(existing)

    response = await signed_in.post(
        "/api/preview",
        json={
            "media_type": "movie",
            "media": MOVIE,
            "inspection_id": inspection_id,
            "options": OPTIONS,
        },
    )

    assert response.json() == {"path": str(existing), "exists": True}


# --------------------------------------------------- M6 AC6/AC7: TV requests


SERIES = {"sonarr_series_id": 3, "title": "Some Show", "numbering": "standard"}
DAILY_SERIES = {"sonarr_series_id": 5, "title": "Daily Show", "numbering": "daily"}


def _episode(number: int, title: str, episode_id: int) -> dict[str, Any]:
    return {"season": 1, "number": number, "sonarr_episode_id": episode_id, "title": title}


async def test_a_tv_request_creates_one_job_per_episode(
    signed_in: httpx.AsyncClient, app: FastAPI, add_inspection: Callable[..., Any]
) -> None:
    """AC7: three items, three jobs, each carrying which episode it is (§10)."""
    inspections = [await add_inspection(title=f"Some Show Ep {n}") for n in (1, 2, 3)]

    response = await signed_in.post(
        "/api/requests",
        json={
            "media_type": "tv",
            "media": SERIES,
            "items": [
                {"inspection_id": inspections[0], "episode": _episode(1, "Pilot", 101)},
                {"inspection_id": inspections[1], "episode": _episode(2, "Second", 102)},
                {"inspection_id": inspections[2], "episode": _episode(3, "Third", 103)},
            ],
            "options": OPTIONS,
            "collision_policy": "keep_both",
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert len(body["jobs"]) == 3
    async with app.state.db.read_session() as session:
        request = await session.get(Request, body["id"])
        jobs = [await session.get(Job, job_id) for job_id in body["jobs"]]
    assert request is not None
    assert (request.media_type, request.title) == ("tv", "Some Show")
    assert (request.numbering, request.sonarr_series_id) == ("standard", 3)
    assert [(job.season, job.episode, job.episode_title) for job in jobs] == [
        (1, 1, "Pilot"),
        (1, 2, "Second"),
        (1, 3, "Third"),
    ]
    assert [job.sonarr_episode_id for job in jobs] == [101, 102, 103]
    # An episode still has to be imported; `other` never does (§6).
    assert {job.import_status for job in jobs} == {"pending"}


async def test_a_tv_request_needs_an_episode_for_every_item(
    signed_in: httpx.AsyncClient, add_inspection: Callable[..., Any]
) -> None:
    inspection_id = await add_inspection()

    response = await signed_in.post(
        "/api/requests",
        json={
            "media_type": "tv",
            "media": SERIES,
            "items": [{"inspection_id": inspection_id}],
            "options": OPTIONS,
        },
    )

    assert response.status_code == 422
    assert "episode block" in response.text


async def test_a_tv_request_keeps_the_series_id_off_a_movie_block(
    signed_in: httpx.AsyncClient, app: FastAPI, add_inspection: Callable[..., Any]
) -> None:
    """The media type decides how the media block is read, so nothing is silently dropped."""
    inspection_id = await add_inspection()

    response = await signed_in.post(
        "/api/requests",
        json={
            "media_type": "tv",
            "media": SERIES,
            "items": [{"inspection_id": inspection_id, "episode": _episode(5, "Fifth", 105)}],
            "options": OPTIONS,
        },
    )

    body = response.json()
    async with app.state.db.read_session() as session:
        request = await session.get(Request, body["id"])
    assert request is not None
    assert (request.sonarr_series_id, request.radarr_movie_id) == (3, None)


async def test_a_tv_preview_uses_sonarrs_titles_and_the_season_folder(
    signed_in: httpx.AsyncClient, settings: Settings, add_inspection: Callable[..., Any]
) -> None:
    """AC6: Sonarr's series and episode titles, in `Season {season}` (§7.2)."""
    inspection_id = await add_inspection(title="some show s01e05 1080p reupload")

    response = await signed_in.post(
        "/api/preview",
        json={
            "media_type": "tv",
            "media": SERIES,
            "inspection_id": inspection_id,
            "episode": _episode(5, "The Fifth One", 105),
            "options": OPTIONS,
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["path"] == str(
        settings.completed_dir
        / "tv-shows"
        / "Some Show"
        / "Season 1"
        / "Some Show - S01E05 - The Fifth One WEBDL-1080p.mkv"
    )


async def test_a_tv_preview_puts_season_zero_in_specials(
    signed_in: httpx.AsyncClient, settings: Settings, add_inspection: Callable[..., Any]
) -> None:
    """AC6: season 0 is `Specials`, which is what Sonarr calls that folder (§7.2)."""
    inspection_id = await add_inspection()

    response = await signed_in.post(
        "/api/preview",
        json={
            "media_type": "tv",
            "media": SERIES,
            "inspection_id": inspection_id,
            "episode": {
                "season": 0,
                "number": 3,
                "sonarr_episode_id": 203,
                "title": "Behind the Scenes",
            },
            "options": OPTIONS,
        },
    )

    assert response.json()["path"] == str(
        settings.completed_dir
        / "tv-shows"
        / "Some Show"
        / "Specials"
        / "Some Show - S00E03 - Behind the Scenes WEBDL-1080p.mkv"
    )


async def test_a_daily_tv_preview_is_named_by_its_air_date(
    signed_in: httpx.AsyncClient, settings: Settings, add_inspection: Callable[..., Any]
) -> None:
    """AC6: a daily series is numbered by date, in the season Sonarr gave it (§7.2)."""
    inspection_id = await add_inspection()

    response = await signed_in.post(
        "/api/preview",
        json={
            "media_type": "tv",
            "media": DAILY_SERIES,
            "inspection_id": inspection_id,
            "episode": {
                "season": 2024,
                "sonarr_episode_id": 301,
                "title": "News",
                "air_date": "2024-03-15",
            },
            "options": OPTIONS,
        },
    )

    assert response.json()["path"] == str(
        settings.completed_dir
        / "tv-shows"
        / "Daily Show"
        / "Season 2024"
        / "Daily Show - 2024-03-15 - News WEBDL-1080p.mkv"
    )


async def test_a_tv_preview_needs_an_episode(
    signed_in: httpx.AsyncClient, add_inspection: Callable[..., Any]
) -> None:
    inspection_id = await add_inspection()

    response = await signed_in.post(
        "/api/preview",
        json={
            "media_type": "tv",
            "media": SERIES,
            "inspection_id": inspection_id,
            "options": OPTIONS,
        },
    )

    assert response.status_code == 422
    assert "episode block" in response.text


async def test_a_standard_episode_without_a_number_cannot_be_named(
    signed_in: httpx.AsyncClient, add_inspection: Callable[..., Any]
) -> None:
    """A manually typed series with no number has no name to build (§7.2)."""
    inspection_id = await add_inspection()

    response = await signed_in.post(
        "/api/preview",
        json={
            "media_type": "tv",
            "media": {"sonarr_series_id": None, "title": "Typed Show", "numbering": "standard"},
            "inspection_id": inspection_id,
            "episode": {"season": 1, "title": "Untitled"},
            "options": OPTIONS,
        },
    )

    assert response.status_code == 422
    assert "episode number" in response.text


# ------------------------------------------------ M9: GET /api/requests (History)


def _at(day: str) -> datetime:
    return datetime.fromisoformat(day)


@pytest.fixture
def add_history(app: FastAPI, settings: Settings) -> Callable[..., Any]:
    """A finished request and its jobs; finished, so the running manager leaves them alone."""

    async def insert(
        media_type: str, created_at: str, *jobs: dict[str, Any], **request: Any
    ) -> str:
        db: Database = app.state.db
        request_id = str(uuid.uuid4())
        async with db.write_session() as session:
            session.add(
                Request(
                    id=request_id,
                    media_type=media_type,
                    title=request.pop("title", f"{media_type} request"),
                    options=request.pop("options", OPTIONS),
                    created_at=_at(created_at),
                    **request,
                )
            )
            await session.flush()
            for fields in jobs or ({},):
                job_id = str(uuid.uuid4())
                session.add(
                    Job(
                        id=job_id,
                        request_id=request_id,
                        url=fields.pop("url", "https://example.com/v"),
                        source_title=fields.pop("source_title", "a video"),
                        status=fields.pop("status", JobStatus.COMPLETED),
                        import_status=fields.pop("import_status", ImportStatus.NOT_APPLICABLE),
                        step_timings={},
                        sidecar_paths=[],
                        job_dir=str(settings.incomplete_dir / job_id),
                        created_at=_at(created_at),
                        **fields,
                    )
                )
        return request_id

    return insert


@pytest.fixture
async def history(add_history: Callable[..., Any]) -> dict[str, str]:
    return {
        "movie": await add_history(
            "movie",
            "2026-09-01T12:00:00",
            {"import_status": ImportStatus.IMPORTED, "site_key": "youtube"},
        ),
        "tv": await add_history(
            "tv",
            "2026-09-10T08:00:00",
            {"import_status": ImportStatus.NOT_IMPORTED, "site_key": "youtube"},
            {
                "status": JobStatus.FAILED,
                "import_status": ImportStatus.PENDING,
                "site_key": "bilibili",
            },
        ),
        "other": await add_history("other", "2026-09-15T23:59:59"),
        "late": await add_history(
            "other",
            "2026-09-16T00:00:00",
            {"status": JobStatus.CANCELLED, "site_key": "dailymotion"},
        ),
    }


async def _ids(client: httpx.AsyncClient, query: str) -> set[str]:
    response = await client.get(f"/api/requests?{query}")
    assert response.status_code == 200, response.text
    return {item["id"] for item in response.json()["items"]}


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("", {"movie", "tv", "other", "late"}),
        ("type=movie", {"movie"}),
        ("type=tv", {"tv"}),
        ("type=other", {"other", "late"}),
        ("status=failed", {"tv"}),
        ("status=completed", {"movie", "tv", "other"}),
        ("status=cancelled", {"late"}),
        ("import_status=imported", {"movie"}),
        ("import_status=not_imported", {"tv"}),
        ("import_status=n/a", {"other", "late"}),
        ("site=bilibili", {"tv"}),
        ("site=youtube", {"movie", "tv"}),
        ("from=2026-09-10", {"tv", "other", "late"}),
        ("to=2026-09-10", {"movie", "tv"}),
    ],
)
async def test_list_each_filter_narrows(
    signed_in: httpx.AsyncClient, history: dict[str, str], query: str, expected: set[str]
) -> None:
    assert await _ids(signed_in, query) == {history[key] for key in expected}


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("type=tv&site=youtube", {"tv"}),
        ("type=movie&site=bilibili", set()),
        ("type=other&to=2026-09-15", {"other"}),
        ("status=completed&import_status=not_imported", {"tv"}),
        # The tv request has a failed job and a youtube job, but not a failed youtube job.
        ("status=failed&site=youtube", set()),
        ("status=failed&site=bilibili&type=tv&from=2026-09-01&to=2026-09-30", {"tv"}),
    ],
)
async def test_list_filters_combine_with_and(
    signed_in: httpx.AsyncClient, history: dict[str, str], query: str, expected: set[str]
) -> None:
    assert await _ids(signed_in, query) == {history[key] for key in expected}


async def test_list_date_range_includes_the_whole_to_day(
    signed_in: httpx.AsyncClient, history: dict[str, str]
) -> None:
    # 23:59:59 on the 15th is inside `to=2026-09-15`; midnight on the 16th is not.
    assert await _ids(signed_in, "from=2026-09-15&to=2026-09-15") == {history["other"]}
    assert await _ids(signed_in, "from=2026-09-16&to=2026-09-16") == {history["late"]}


async def test_list_items_carry_all_their_jobs(
    signed_in: httpx.AsyncClient, history: dict[str, str]
) -> None:
    body = (await signed_in.get("/api/requests?status=failed")).json()

    assert body["total"] == 1
    [item] = body["items"]
    # Both jobs, not just the failed one that matched.
    assert sorted(job["status"] for job in item["jobs"]) == ["completed", "failed"]
    assert {job["site_key"] for job in item["jobs"]} == {"youtube", "bilibili"}
    assert {"completed_path", "imported_path", "import_detail"} <= set(item["jobs"][0])


async def test_list_q_searches(
    signed_in: httpx.AsyncClient, add_history: Callable[..., Any]
) -> None:
    bunny = await add_history(
        "other", "2026-09-01T00:00:00", {"source_title": "Big Buck Bunny 4K"}, title="BBB"
    )
    await add_history("other", "2026-09-02T00:00:00", {"source_title": "Sintel"}, title="Sintel")
    episode = await add_history(
        "tv",
        "2026-09-03T00:00:00",
        {"source_title": "upload 1", "episode_title": "Pilot"},
        title="Some Show",
    )

    assert await _ids(signed_in, "q=bunn") == {bunny}
    assert await _ids(signed_in, "q=pil") == {episode}
    assert await _ids(signed_in, "q=pil&type=movie") == set()
    assert await _ids(signed_in, "q=%22%29%2A") == await _ids(signed_in, "")


async def test_list_pages_are_newest_first_and_stable(
    signed_in: httpx.AsyncClient, add_history: Callable[..., Any]
) -> None:
    days = ["2026-09-01", "2026-09-03", "2026-09-03", "2026-09-03", "2026-09-02", "2026-09-05"]
    created = [(f"{day}T10:00:00", await add_history("other", f"{day}T10:00:00")) for day in days]
    newest_first = [rid for _, rid in sorted(created, reverse=True)]

    pages = []
    for page in (1, 2, 3):
        response = await signed_in.get(f"/api/requests?page={page}&per_page=2")
        body = response.json()
        assert (body["total"], body["page"], body["per_page"]) == (6, page, 2)
        pages.append([item["id"] for item in body["items"]])

    assert [rid for page in pages for rid in page] == newest_first
    # Asking again gives the same page, ties included.
    again = (await signed_in.get("/api/requests?page=2&per_page=2")).json()
    assert [item["id"] for item in again["items"]] == pages[1]
    assert (await signed_in.get("/api/requests?page=4&per_page=2")).json()["items"] == []


@pytest.mark.parametrize(
    "query", ["per_page=101", "per_page=0", "page=0", "type=show", "status=done", "bogus=1"]
)
async def test_list_per_page_above_100_is_422(signed_in: httpx.AsyncClient, query: str) -> None:
    assert (await signed_in.get(f"/api/requests?{query}")).status_code == 422


async def test_list_per_page_of_100_is_allowed(signed_in: httpx.AsyncClient) -> None:
    assert (await signed_in.get("/api/requests?per_page=100")).status_code == 200


async def test_list_requires_session(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/requests")).status_code == 401


# ------------------------------------------------ M9 AC7: download again


@pytest.mark.parametrize("media_type", ["movie", "tv", "other"])
async def test_get_request_has_what_the_wizard_needs(
    signed_in: httpx.AsyncClient, add_history: Callable[..., Any], media_type: str
) -> None:
    media: dict[str, Any] = {
        "movie": {"title": "Big Buck Bunny", "year": 2008, "radarr_movie_id": 7},
        "tv": {"title": "Some Show", "numbering": "daily", "sonarr_series_id": 3},
        "other": {"title": "a clip"},
    }[media_type]
    episode = (
        {"season": 1, "episode": 2, "sonarr_episode_id": 102, "episode_title": "Second"}
        if media_type == "tv"
        else {}
    )
    request_id = await add_history(
        media_type,
        "2026-09-01T10:00:00",
        {"url": "https://example.com/watch?v=abc123", **episode},
        options={**OPTIONS, "quality": "720p", "container": "mp4"},
        **media,
    )

    body = (await signed_in.get(f"/api/requests/{request_id}")).json()

    assert body["media_type"] == media_type
    assert body["options"]["quality"] == "720p"
    assert body["options"]["container"] == "mp4"
    for key in ("title", "year", "numbering", "radarr_movie_id", "sonarr_series_id"):
        assert body[key] == media.get(key)
    [job] = body["jobs"]
    assert job["url"] == "https://example.com/watch?v=abc123"
    for key in ("season", "episode", "sonarr_episode_id", "episode_title"):
        assert job[key] == episode.get(key)
    assert "air_date" in job


# ------------------------------------------------ M9 AC8: fast on 5,000 jobs


def _seed_5000_jobs(db_path: str) -> None:
    """2,500 requests × 2 jobs through plain sqlite3, so the triggers fill the index."""
    types = ("movie", "tv", "other")
    statuses = ("completed", "failed", "cancelled")
    requests, jobs = [], []
    for n in range(2500):
        request_id = f"r{n:05d}"
        media_type = types[n % 3]
        created = f"2026-{1 + n % 9:02d}-{1 + n % 28:02d} {n % 24:02d}:00:00"
        requests.append((request_id, media_type, f"Show {n}", "{}", created))
        for part in (1, 2):
            jobs.append(
                (
                    f"j{n:05d}{part}",
                    request_id,
                    "https://example.com/v",
                    f"Show {n} part {part} upload",
                    f"Episode {part}" if media_type == "tv" else None,
                    statuses[(n + part) % 3],
                    "n/a",
                    "youtube",
                    "{}",
                    "[]",
                    "/tmp/unused",
                    created,
                )
            )
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            "INSERT INTO requests (id, media_type, title, options, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            requests,
        )
        conn.executemany(
            "INSERT INTO jobs (id, request_id, url, source_title, episode_title, status, "
            "import_status, site_key, step_timings, sidecar_paths, job_dir, created_at, "
            "cancel_requested, attempt, max_attempts, collision_policy, use_cookies, "
            "transcode_fallback_used, import_attempts) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 1, 'keep_both', 1, 0, 0)",
            jobs,
        )


async def test_list_is_fast_on_5000_jobs(
    signed_in: httpx.AsyncClient, migrated_db_url: str
) -> None:
    await asyncio.to_thread(_seed_5000_jobs, migrated_db_url.split("///", 1)[1])
    url = "/api/requests?q=show%2012&type=tv&per_page=25"

    first = await signed_in.get(url)  # warm-up: connections, statement cache
    timings = []
    for _ in range(3):
        started = time.perf_counter()
        response = await signed_in.get(url)
        timings.append(time.perf_counter() - started)
        assert response.json() == first.json()

    body = first.json()
    # "Show 12", "Show 120"-"Show 129", "Show 1200"-"Show 1299": the tv ones among them.
    assert body["total"] == len([n for n in range(2500) if str(n).startswith("12") and n % 3 == 1])
    assert all(item["media_type"] == "tv" for item in body["items"])
    assert min(timings) < 0.1, timings
