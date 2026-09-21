"""`POST /api/requests`, `GET /api/requests/{id}` and `POST /api/preview` (requirements §11)."""

from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.config import Settings
from app.db.base import utcnow
from app.db.session import Database
from app.inspections.models import Inspection
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
