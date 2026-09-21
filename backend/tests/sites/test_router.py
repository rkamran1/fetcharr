import time
from datetime import timedelta

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select, update

from app.db.base import utcnow
from app.inspections.models import Inspection
from app.settings.utils import decrypt
from app.sites.models import SiteCookies
from tests.conftest import (
    CANARY,
    cookie_file,
    cookie_line,
    setup_account,
    upload_cookies,
)
from tests.fake_ytdlp import FakeYtdlp

YOUTUBE_FILE = cookie_file(
    cookie_line(".youtube.com"),
    f"#HttpOnly_{cookie_line('.youtube.com', 'HSID')}",
    cookie_line(".google.com", "NID"),
    cookie_line(".github.com", "user_session", "github-only-value"),
)
ENDPOINTS = [
    ("GET", "/api/sites", None),
    ("POST", "/api/sites", {"key": "vimeo", "domains": ["vimeo.com"]}),
    ("DELETE", "/api/sites/vimeo", None),
    ("PUT", "/api/sites/youtube/cookies", {"text": YOUTUBE_FILE}),
    ("DELETE", "/api/sites/youtube/cookies", None),
]


def _days(days: float) -> int:
    return int(time.time() + days * 86400)


async def _site(client: httpx.AsyncClient, key: str) -> dict:
    response = await client.get("/api/sites")
    assert response.status_code == 200
    return next(site for site in response.json() if site["key"] == key)


async def _row(app: FastAPI, key: str) -> SiteCookies | None:
    async with app.state.db.read_session() as session:
        return await session.get(SiteCookies, key)


@pytest.mark.parametrize(("method", "path", "body"), ENDPOINTS)
async def test_sites_endpoints_require_session(
    client: httpx.AsyncClient, method: str, path: str, body: dict | None
) -> None:
    response = await client.request(method, path, json=body)

    assert response.status_code == 401


async def test_list_sites_has_the_builtins(client: httpx.AsyncClient) -> None:
    await setup_account(client)

    response = await client.get("/api/sites")

    assert response.status_code == 200
    assert [(s["key"], s["builtin"], s["status"]) for s in response.json()] == [
        ("bilibili", True, "none"),
        ("dailymotion", True, "none"),
        ("youtube", True, "none"),
    ]
    youtube = response.json()[2]
    assert youtube["domains"] == ["youtube.com", "youtu.be", "youtube-nocookie.com", "google.com"]
    assert youtube["cookie_count"] is None


async def test_upload_rejects_non_netscape_file(app: FastAPI, client: httpx.AsyncClient) -> None:
    await setup_account(client)

    response = await client.put(
        "/api/sites/youtube/cookies", json={"text": '{"cookies": "json export"}'}
    )

    assert response.status_code == 422
    assert "Netscape" in response.json()["detail"]
    assert await _row(app, "youtube") is None


async def test_upload_rejects_malformed_line(app: FastAPI, client: httpx.AsyncClient) -> None:
    await setup_account(client)
    text = cookie_file(cookie_line(".youtube.com"), ".youtube.com\tTRUE\t/\tSID")

    response = await client.put("/api/sites/youtube/cookies", json={"text": text})

    assert response.status_code == 422
    assert response.json()["detail"] == "line 4: expected 7 tab-separated fields"
    assert await _row(app, "youtube") is None


async def test_upload_keeps_only_site_domains(app: FastAPI, client: httpx.AsyncClient) -> None:
    await setup_account(client)

    response = await upload_cookies(client, "youtube", YOUTUBE_FILE)

    body = response.json()
    assert body["warning"] is None
    assert body["site"]["cookie_count"] == 3
    assert body["site"]["status"] == "valid"
    row = await _row(app, "youtube")
    assert row is not None
    stored = decrypt(row.enc_blob, app.state.secret_key)
    assert stored is not None
    assert "github-only-value" not in stored
    assert stored.count(CANARY) == 3


async def test_upload_without_site_domains_warns_and_keeps_existing(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    await setup_account(client)
    await upload_cookies(client, "youtube", YOUTUBE_FILE)
    before = await _row(app, "youtube")

    response = await upload_cookies(
        client, "youtube", cookie_file(cookie_line(".github.com", "user_session"))
    )

    body = response.json()
    assert "nothing was saved" in body["warning"]
    assert body["site"]["cookie_count"] == 3
    after = await _row(app, "youtube")
    assert before is not None and after is not None
    assert after.enc_blob == before.enc_blob


async def test_upload_is_encrypted_and_never_returned(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    await setup_account(client)

    uploaded = await upload_cookies(client, "youtube", YOUTUBE_FILE)
    listed = await client.get("/api/sites")

    row = await _row(app, "youtube")
    assert row is not None
    assert CANARY not in row.enc_blob
    assert "youtube.com" not in row.enc_blob
    assert CANARY not in uploaded.text
    assert CANARY not in listed.text
    assert "github-only-value" not in uploaded.text


async def test_reupload_replaces(app: FastAPI, client: httpx.AsyncClient) -> None:
    await setup_account(client)
    await upload_cookies(client, "youtube", YOUTUBE_FILE)
    first = await _row(app, "youtube")

    second_file = cookie_file(cookie_line(".youtube.com", "SID", "replacement", _days(30)))
    response = await upload_cookies(client, "youtube", second_file)

    assert response.json()["site"]["cookie_count"] == 1
    row = await _row(app, "youtube")
    assert first is not None and row is not None
    assert row.enc_blob != first.enc_blob
    stored = decrypt(row.enc_blob, app.state.secret_key)
    assert stored is not None
    assert "replacement" in stored
    assert CANARY not in stored


@pytest.mark.parametrize(
    ("expires", "status"),
    [(_days(3), "expiring"), (_days(-3), "expired"), (_days(60), "valid")],
)
async def test_list_sites_reports_status(
    client: httpx.AsyncClient, expires: int, status: str
) -> None:
    await setup_account(client)
    await upload_cookies(
        client, "bilibili", cookie_file(cookie_line(".bilibili.com", "SESSDATA", "v", expires))
    )

    site = await _site(client, "bilibili")

    assert site["status"] == status
    assert site["earliest_expiry"] is not None


async def test_upload_clears_flag(app: FastAPI, client: httpx.AsyncClient) -> None:
    await setup_account(client)
    await upload_cookies(client, "youtube", YOUTUBE_FILE)
    async with app.state.db.write_session() as session:
        await session.execute(
            update(SiteCookies)
            .where(SiteCookies.site_key == "youtube")
            .values(flagged_invalid=True)
        )
    assert (await _site(client, "youtube"))["status"] == "flagged"

    await upload_cookies(client, "youtube", YOUTUBE_FILE)

    assert (await _site(client, "youtube"))["status"] == "valid"


async def test_upload_forgets_cached_inspections(
    app: FastAPI, client: httpx.AsyncClient, fake_ytdlp: FakeYtdlp
) -> None:
    await setup_account(client)
    url = "https://www.youtube.com/watch?v=aqz-KE-bpKQ"
    assert (await client.post("/api/inspect", json={"url": url})).status_code == 200

    await upload_cookies(client, "youtube", YOUTUBE_FILE)
    assert (await client.post("/api/inspect", json={"url": url})).status_code == 200

    # The second inspect ran yt-dlp again, this time with the cookies.
    assert len(fake_ytdlp.calls) == 2
    assert "--cookies" in fake_ytdlp.calls[1]


async def test_custom_site_lifecycle(
    app: FastAPI, client: httpx.AsyncClient, fake_ytdlp: FakeYtdlp
) -> None:
    await setup_account(client)

    created = await client.post(
        "/api/sites", json={"key": "Vimeo", "domains": ["Vimeo.com", ".vimeocdn.com"]}
    )

    assert created.status_code == 201
    assert created.json()["key"] == "vimeo"
    assert created.json()["domains"] == ["vimeo.com", "vimeocdn.com"]
    assert created.json()["builtin"] is False
    assert (await _site(client, "vimeo"))["status"] == "none"

    fake_ytdlp.returns_json("dailymotion.json")
    inspected = await client.post("/api/inspect", json={"url": "https://player.vimeo.com/v/1"})
    assert inspected.json()["site_key"] == "vimeo"

    await upload_cookies(
        client, "vimeo", cookie_file(cookie_line(".vimeo.com", "vuid", "v", _days(90)))
    )
    deleted = await client.delete("/api/sites/vimeo")

    assert deleted.status_code == 204
    assert [s["key"] for s in (await client.get("/api/sites")).json()] == [
        "bilibili",
        "dailymotion",
        "youtube",
    ]
    assert await _row(app, "vimeo") is None


async def test_builtin_site_cannot_be_deleted(client: httpx.AsyncClient) -> None:
    await setup_account(client)

    response = await client.delete("/api/sites/youtube")

    assert response.status_code == 409
    assert (await _site(client, "youtube"))["builtin"] is True


async def test_duplicate_site_is_409(client: httpx.AsyncClient) -> None:
    await setup_account(client)

    response = await client.post("/api/sites", json={"key": "youtube", "domains": ["x.com"]})

    assert response.status_code == 409


@pytest.mark.parametrize(
    "body",
    [
        {"key": "has space", "domains": ["x.com"]},
        {"key": "-dash", "domains": ["x.com"]},
        {"key": "ok", "domains": []},
        {"key": "ok", "domains": ["not a domain"]},
        {"key": "ok", "domains": ["localhost"]},
    ],
)
async def test_invalid_site_is_422(client: httpx.AsyncClient, body: dict) -> None:
    await setup_account(client)

    response = await client.post("/api/sites", json=body)

    assert response.status_code == 422


async def test_delete_cookies(app: FastAPI, client: httpx.AsyncClient) -> None:
    await setup_account(client)
    await upload_cookies(client, "youtube", YOUTUBE_FILE)

    first = await client.delete("/api/sites/youtube/cookies")
    again = await client.delete("/api/sites/youtube/cookies")

    assert (first.status_code, again.status_code) == (204, 204)
    assert await _row(app, "youtube") is None
    assert (await _site(client, "youtube"))["status"] == "none"


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("DELETE", "/api/sites/nope", None),
        ("PUT", "/api/sites/nope/cookies", {"text": YOUTUBE_FILE}),
        ("DELETE", "/api/sites/nope/cookies", None),
    ],
)
async def test_unknown_site_is_404(
    client: httpx.AsyncClient, method: str, path: str, body: dict | None
) -> None:
    await setup_account(client)

    response = await client.request(method, path, json=body)

    assert response.status_code == 404


async def test_inspections_keep_other_sites_cache(app: FastAPI, client: httpx.AsyncClient) -> None:
    """Only the uploaded site's cached inspections are forgotten."""
    await setup_account(client)
    now = utcnow()
    async with app.state.db.write_session() as session:
        for key in ("youtube", "bilibili"):
            session.add(
                Inspection(
                    url=f"https://{key}.test",
                    site_key=key,
                    info={},
                    created_at=now,
                    expires_at=now + timedelta(minutes=30),
                )
            )

    await upload_cookies(client, "youtube", YOUTUBE_FILE)

    async with app.state.db.read_session() as session:
        left = list(await session.scalars(select(Inspection.site_key)))
    assert left == ["bilibili"]
