import uuid
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select, update

from app.db.base import utcnow
from app.inspections.models import Inspection
from app.inspections.utils import PLAYLIST_MESSAGE
from app.jobs.constants import ImportStatus, JobStatus
from app.jobs.models import Job
from app.requests.models import Request
from app.sites.models import SiteCookies
from app.ytdlp import inspect
from app.ytdlp.inspect import build_inspect_argv
from app.ytdlp.runtime import detect_js_runtime
from tests.conftest import cookie_file, cookie_line, exists, setup_account, upload_cookies
from tests.fake_ytdlp import FakeYtdlp

YOUTUBE_URL = "https://www.youtube.com/watch?v=aqz-KE-bpKQ"
DAILYMOTION_URL = "https://www.dailymotion.com/video/x3z49k"


async def _rows(app: FastAPI) -> list[Inspection]:
    async with app.state.db.read_session() as session:
        return list(await session.scalars(select(Inspection).order_by(Inspection.id)))


async def test_inspect_requires_session(client: httpx.AsyncClient, fake_ytdlp: FakeYtdlp) -> None:
    response = await client.post("/api/inspect", json={"url": YOUTUBE_URL})

    assert response.status_code == 401
    assert fake_ytdlp.calls == []


async def test_inspect_youtube_returns_normalised_info(
    app: FastAPI, client: httpx.AsyncClient, fake_ytdlp: FakeYtdlp
) -> None:
    await setup_account(client)

    response = await client.post("/api/inspect", json={"url": YOUTUBE_URL})

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "inspection_id",
        "site_key",
        "title",
        "uploader",
        "thumbnail",
        "duration",
        "webpage_url",
        "extractor",
        "id",
        "upload_date",
        "release_year",
        "video_heights",
        "video_codecs",
        "audio_tracks",
        "has_hdr",
        "subtitles",
        "automatic_captions",
        "estimated_sizes",
        "stream_type",
        "auto",
        "previous_downloads",
    }
    assert body["title"] == "Big Buck Bunny 60fps 4K - Official Blender Foundation Short Film"
    assert body["video_heights"] == [2160, 1440, 1080, 720, 480, 360, 240, 144]
    assert body["video_heights"] == sorted(set(body["video_heights"]), reverse=True)
    assert body["stream_type"] == "dash"
    assert body["estimated_sizes"]["2160"] == 1362269481 + 10271496
    rows = await _rows(app)
    # M8 fills the site the URL belongs to (M4 left it empty).
    assert body["site_key"] == "youtube"
    assert [(r.id, r.url, r.site_key) for r in rows] == [
        (body["inspection_id"], YOUTUBE_URL, "youtube")
    ]
    assert rows[0].expires_at - rows[0].created_at == timedelta(minutes=30)
    assert rows[0].info["title"] == body["title"]


async def test_inspect_runs_ytdlp_with_inspect_argv(
    client: httpx.AsyncClient, fake_ytdlp: FakeYtdlp
) -> None:
    await setup_account(client)
    url = f"{YOUTUBE_URL}&list=PL123"

    response = await client.post("/api/inspect", json={"url": url})

    assert response.status_code == 200
    assert fake_ytdlp.calls == [build_inspect_argv(url, detect_js_runtime())]
    assert "--no-playlist" in fake_ytdlp.calls[0]


async def test_inspect_rejects_playlist(
    app: FastAPI, client: httpx.AsyncClient, fake_ytdlp: FakeYtdlp
) -> None:
    await setup_account(client)
    fake_ytdlp.returns_json("playlist.json")

    response = await client.post(
        "/api/inspect", json={"url": "https://www.youtube.com/playlist?list=PL123"}
    )

    assert response.status_code == 422
    assert response.json() == {
        "detail": PLAYLIST_MESSAGE,
        "needs_cookies": False,
        "site_key": None,
    }
    assert await _rows(app) == []


async def test_inspect_needs_cookies(client: httpx.AsyncClient, fake_ytdlp: FakeYtdlp) -> None:
    await setup_account(client)
    fake_ytdlp.fails_with("age.txt")

    response = await client.post("/api/inspect", json={"url": YOUTUBE_URL})

    assert response.status_code == 422
    body = response.json()
    assert body["needs_cookies"] is True
    assert body["detail"].startswith("Sign in to confirm your age")


async def test_inspect_unsupported_url(client: httpx.AsyncClient, fake_ytdlp: FakeYtdlp) -> None:
    await setup_account(client)
    fake_ytdlp.fails_with("unsupported.txt")

    response = await client.post("/api/inspect", json={"url": "https://example.com/"})

    assert response.status_code == 422
    assert response.json() == {
        "detail": "Unsupported URL",
        "needs_cookies": False,
        "site_key": None,
    }


async def test_inspect_timeout_returns_504(
    client: httpx.AsyncClient, fake_ytdlp: FakeYtdlp, monkeypatch: pytest.MonkeyPatch
) -> None:
    await setup_account(client)
    monkeypatch.setattr(inspect, "INSPECT_TIMEOUT_S", 1.0)
    fake_ytdlp.hangs()

    response = await client.post("/api/inspect", json={"url": DAILYMOTION_URL})

    assert response.status_code == 504
    assert response.json()["needs_cookies"] is False


async def test_inspect_other_failure_returns_502(
    client: httpx.AsyncClient, fake_ytdlp: FakeYtdlp
) -> None:
    await setup_account(client)
    fake_ytdlp.fails_with("network.txt")

    response = await client.post("/api/inspect", json={"url": YOUTUBE_URL})

    assert response.status_code == 502
    assert response.json()["detail"].startswith("ERROR: [youtube] aqz-KE-bpKQ: Unable to download")


async def test_inspect_reuses_cache_within_30_minutes(
    client: httpx.AsyncClient, fake_ytdlp: FakeYtdlp
) -> None:
    await setup_account(client)

    first = await client.post("/api/inspect", json={"url": YOUTUBE_URL})
    second = await client.post("/api/inspect", json={"url": YOUTUBE_URL})

    assert first.status_code == second.status_code == 200
    assert second.json() == first.json()
    assert len(fake_ytdlp.calls) == 1


async def test_inspect_runs_again_after_expiry(
    app: FastAPI, client: httpx.AsyncClient, fake_ytdlp: FakeYtdlp
) -> None:
    await setup_account(client)
    first = await client.post("/api/inspect", json={"url": YOUTUBE_URL})
    async with app.state.db.write_session() as session:
        await session.execute(update(Inspection).values(expires_at=utcnow() - timedelta(seconds=1)))

    second = await client.post("/api/inspect", json={"url": YOUTUBE_URL})

    assert second.status_code == 200
    assert len(fake_ytdlp.calls) == 2
    assert second.json()["inspection_id"] != first.json()["inspection_id"]
    assert [r.id for r in await _rows(app)] == [second.json()["inspection_id"]]


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/video.mp4",
        "file:///etc/passwd",
        "javascript:alert(1)",
        "-o/tmp/x",
        "--exec=id",
        "not a url",
        "https://",
    ],
)
async def test_inspect_rejects_bad_urls(
    client: httpx.AsyncClient, fake_ytdlp: FakeYtdlp, url: str
) -> None:
    await setup_account(client)

    response = await client.post("/api/inspect", json={"url": url})

    assert response.status_code == 422
    assert fake_ytdlp.calls == []


# ------------------------------------------------------------------ M8: cookies (§8)

YOUTUBE_COOKIES = cookie_file(cookie_line(".youtube.com"))


async def _flagged(app: FastAPI) -> bool:
    async with app.state.db.read_session() as session:
        row = await session.get(SiteCookies, "youtube")
    assert row is not None
    return row.flagged_invalid


async def test_inspect_uses_site_cookies(
    app: FastAPI, client: httpx.AsyncClient, fake_ytdlp: FakeYtdlp
) -> None:
    await setup_account(client)
    await upload_cookies(client, "youtube", YOUTUBE_COOKIES)

    response = await client.post("/api/inspect", json={"url": YOUTUBE_URL})

    assert response.status_code == 200
    [seen] = fake_ytdlp.cookies_seen
    argv = fake_ytdlp.calls[0]
    assert argv[argv.index("--cookies") + 1] == seen["path"]
    assert seen["mode"] == 0o600
    assert seen["text"] == YOUTUBE_COOKIES
    assert not exists(Path(seen["path"]))
    assert not exists(Path(seen["path"]).parent)
    async with app.state.db.read_session() as session:
        row = await session.get(SiteCookies, "youtube")
    assert row is not None and row.last_used_at is not None


async def test_inspect_deletes_cookies_after_failure(
    client: httpx.AsyncClient, fake_ytdlp: FakeYtdlp
) -> None:
    await setup_account(client)
    await upload_cookies(client, "youtube", YOUTUBE_COOKIES)
    fake_ytdlp.fails_with("unavailable.txt")

    response = await client.post("/api/inspect", json={"url": YOUTUBE_URL})

    assert response.status_code == 422
    [seen] = fake_ytdlp.cookies_seen
    assert seen["mode"] == 0o600
    assert not exists(Path(seen["path"]).parent)


async def test_inspect_unmatched_host_gets_no_cookies(
    app: FastAPI, client: httpx.AsyncClient, fake_ytdlp: FakeYtdlp
) -> None:
    await setup_account(client)
    await upload_cookies(client, "youtube", YOUTUBE_COOKIES)
    fake_ytdlp.returns_json("dailymotion.json")

    response = await client.post("/api/inspect", json={"url": "https://example.com/v/1"})

    assert response.status_code == 200
    assert response.json()["site_key"] is None
    assert "--cookies" not in fake_ytdlp.calls[0]
    assert fake_ytdlp.cookies_seen == []


async def test_inspect_auth_error_flags_site(
    app: FastAPI, client: httpx.AsyncClient, fake_ytdlp: FakeYtdlp
) -> None:
    await setup_account(client)
    await upload_cookies(client, "youtube", YOUTUBE_COOKIES)
    fake_ytdlp.fails_with("members_only.txt")

    response = await client.post("/api/inspect", json={"url": YOUTUBE_URL})

    assert response.status_code == 422
    assert response.json()["needs_cookies"] is True
    assert response.json()["site_key"] == "youtube"
    assert await _flagged(app) is True

    await upload_cookies(client, "youtube", YOUTUBE_COOKIES)
    assert await _flagged(app) is False


async def test_inspect_other_errors_do_not_flag(
    app: FastAPI, client: httpx.AsyncClient, fake_ytdlp: FakeYtdlp
) -> None:
    await setup_account(client)
    await upload_cookies(client, "youtube", YOUTUBE_COOKIES)
    fake_ytdlp.fails_with("not_found.txt")

    await client.post("/api/inspect", json={"url": YOUTUBE_URL})

    assert await _flagged(app) is False


async def test_inspect_needs_cookies_names_the_site(
    client: httpx.AsyncClient, fake_ytdlp: FakeYtdlp
) -> None:
    """Without cookies, the error still says which site to add them for."""
    await setup_account(client)
    fake_ytdlp.fails_with("login_required.txt")

    response = await client.post("/api/inspect", json={"url": "https://www.bilibili.com/video/BV1"})

    assert response.json()["needs_cookies"] is True
    assert response.json()["site_key"] == "bilibili"
    assert "--cookies" not in fake_ytdlp.calls[0]


# ------------------------------------------------ M9 AC5: already downloaded


async def _add_download(app: FastAPI, created_at: datetime, **fields: object) -> str:
    """A request and one job for the fixture's video (youtube / aqz-KE-bpKQ)."""
    request_id, job_id = str(uuid.uuid4()), str(uuid.uuid4())
    media_type = str(fields.pop("media_type", "movie"))
    async with app.state.db.write_session() as session:
        session.add(
            Request(
                id=request_id,
                media_type=media_type,
                title="Big Buck Bunny",
                options={},
                created_at=created_at,
            )
        )
        await session.flush()
        session.add(
            Job(
                id=job_id,
                request_id=request_id,
                url=YOUTUBE_URL,
                extractor=fields.pop("extractor", "youtube"),
                video_id=fields.pop("video_id", "aqz-KE-bpKQ"),
                status=fields.pop("status", JobStatus.COMPLETED),
                step_timings={},
                sidecar_paths=[],
                job_dir="/tmp/unused",
                created_at=created_at,
                **fields,
            )
        )
    return job_id


async def test_inspect_lists_previous_downloads(
    app: FastAPI, client: httpx.AsyncClient, fake_ytdlp: FakeYtdlp
) -> None:
    await setup_account(client)
    imported = await _add_download(
        app,
        datetime(2026, 9, 1, 10),
        import_status=ImportStatus.IMPORTED,
        completed_path="/web-downloads/completed/movies/BBB (2008)/BBB (2008).mkv",
        imported_path="/movies/BBB (2008)/BBB (2008).mkv",
    )
    kept = await _add_download(
        app,
        datetime(2026, 9, 5, 10),
        media_type="other",
        import_status=ImportStatus.NOT_APPLICABLE,
        completed_path="/web-downloads/completed/other/BBB [aqz-KE-bpKQ].mkv",
    )
    # Not downloads of this video: another extractor's id, and jobs that never finished.
    await _add_download(app, datetime(2026, 9, 6), extractor="dailymotion")
    await _add_download(app, datetime(2026, 9, 6), status=JobStatus.FAILED)
    await _add_download(app, datetime(2026, 9, 6), status=JobStatus.CANCELLED)

    response = await client.post("/api/inspect", json={"url": YOUTUBE_URL})

    assert response.status_code == 200
    assert response.json()["previous_downloads"] == [
        {
            "job_id": kept,
            "created_at": "2026-09-05T10:00:00",
            "media_type": "other",
            "path": "/web-downloads/completed/other/BBB [aqz-KE-bpKQ].mkv",
            "import_status": "n/a",
        },
        {
            "job_id": imported,
            "created_at": "2026-09-01T10:00:00",
            "media_type": "movie",
            "path": "/movies/BBB (2008)/BBB (2008).mkv",
            "import_status": "imported",
        },
    ]


async def test_inspect_of_a_new_video_has_no_previous_downloads(
    client: httpx.AsyncClient, fake_ytdlp: FakeYtdlp
) -> None:
    await setup_account(client)

    response = await client.post("/api/inspect", json={"url": YOUTUBE_URL})

    assert response.json()["previous_downloads"] == []


async def test_previous_downloads_are_fresh_on_a_cached_inspection(
    app: FastAPI, client: httpx.AsyncClient, fake_ytdlp: FakeYtdlp
) -> None:
    await setup_account(client)
    first = await client.post("/api/inspect", json={"url": YOUTUBE_URL})
    job_id = await _add_download(app, datetime(2026, 9, 21), media_type="other")

    second = await client.post("/api/inspect", json={"url": YOUTUBE_URL})

    assert len(fake_ytdlp.calls) == 1  # served from the cache
    assert first.json()["previous_downloads"] == []
    assert [entry["job_id"] for entry in second.json()["previous_downloads"]] == [job_id]
