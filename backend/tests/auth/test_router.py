import time
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from argon2 import PasswordHasher
from fastapi import FastAPI
from sqlalchemy import select, update

from app.auth import utils
from app.auth.models import Account, AuthSession
from app.auth.utils import COOKIE_NAME, SESSION_LIFETIME, hash_token
from app.config import Settings
from app.db.base import utcnow
from app.main import create_app
from tests.conftest import (
    PASSWORD,
    USERNAME,
    create_api_key,
    login,
    make_client,
    setup_account,
)

THIRTY_DAYS = 30 * 24 * 60 * 60


async def _account(app: FastAPI) -> Account | None:
    async with app.state.db.read_session() as session:
        return await session.get(Account, 1)


async def _sessions(app: FastAPI) -> list[AuthSession]:
    async with app.state.db.read_session() as session:
        return list((await session.scalars(select(AuthSession))).all())


def _set_cookie(response: httpx.Response) -> str:
    [header] = [h for h in response.headers.get_list("set-cookie") if h.startswith(COOKIE_NAME)]
    return header


# --- AC1: state -------------------------------------------------------------------------


async def test_state_requires_setup_without_account(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/auth/state")

    assert response.status_code == 200
    assert response.json() == {"setup_required": True}


async def test_state_after_setup(client: httpx.AsyncClient) -> None:
    await setup_account(client)
    client.cookies.clear()

    response = await client.get("/api/auth/state")

    assert response.status_code == 200
    assert response.json() == {"setup_required": False}


# --- AC2: setup -------------------------------------------------------------------------


async def test_setup_creates_account_and_session(app: FastAPI, client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/auth/setup", json={"username": f"  {USERNAME} ", "password": PASSWORD}
    )

    assert response.status_code == 201
    assert response.json() == {"username": USERNAME}
    assert COOKIE_NAME in _set_cookie(response)
    me = await client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json() == {"username": USERNAME}
    account = await _account(app)
    assert account is not None
    assert account.password_hash.startswith("$argon2id$")
    assert len(await _sessions(app)) == 1


async def test_setup_twice_returns_409(app: FastAPI, client: httpx.AsyncClient) -> None:
    await setup_account(client)
    before = await _account(app)

    response = await client.post(
        "/api/auth/setup", json={"username": "intruder", "password": "another password"}
    )

    assert response.status_code == 409
    after = await _account(app)
    assert before is not None and after is not None
    assert (after.username, after.password_hash) == (before.username, before.password_hash)


async def test_setup_rejects_short_password(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/auth/setup", json={"username": USERNAME, "password": "short"}
    )

    assert response.status_code == 422


# --- AC3: login -------------------------------------------------------------------------


async def test_login_sets_session_cookie(app: FastAPI, client: httpx.AsyncClient) -> None:
    await setup_account(client)
    client.cookies.clear()

    response = await login(client)

    assert response.status_code == 200
    assert response.json() == {"username": USERNAME}
    cookie = _set_cookie(response).lower()
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert f"max-age={THIRTY_DAYS}" in cookie
    assert "path=/" in cookie
    assert "secure" not in cookie
    assert (await client.get("/api/auth/me")).status_code == 200
    account = await _account(app)
    assert account is not None and account.last_login_at is not None


async def test_login_cookie_secure_when_configured(migrated_db_url: str, static_dir: Path) -> None:
    settings = Settings(database_url=migrated_db_url, cookie_secure=True)
    application = create_app(settings, static_dir=static_dir)
    async with application.router.lifespan_context(application), make_client(application) as c:
        setup = await setup_account(c)
        response = await login(c)

    assert "secure" in _set_cookie(setup).lower()
    assert "secure" in _set_cookie(response).lower()


@pytest.mark.parametrize(
    ("username", "password"), [(USERNAME, "wrong password"), ("someone", PASSWORD)]
)
async def test_login_wrong_credentials_401_no_cookie(
    client: httpx.AsyncClient, username: str, password: str
) -> None:
    await setup_account(client)
    client.cookies.clear()

    response = await client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )

    assert response.status_code == 401
    assert "set-cookie" not in response.headers


# --- AC4: rate limit --------------------------------------------------------------------


async def test_login_rate_limited_per_ip(app: FastAPI, client: httpx.AsyncClient) -> None:
    await setup_account(client)
    async with make_client(app, ip="10.0.0.1") as a, make_client(app, ip="10.0.0.2") as b:
        for _ in range(5):
            assert (await login(a, password="wrong password")).status_code == 401

        blocked = await login(a)
        allowed = await login(b)

    assert blocked.status_code == 429
    assert 1 <= int(blocked.headers["retry-after"]) <= 60
    assert "set-cookie" not in blocked.headers
    assert allowed.status_code == 200


# --- AC6: API key -----------------------------------------------------------------------


async def test_api_key_authenticates(client: httpx.AsyncClient) -> None:
    await setup_account(client)
    api_key = await create_api_key(client)
    client.cookies.clear()

    response = await client.get("/api/auth/me", headers={"X-Api-Key": api_key})

    assert response.status_code == 200
    assert response.json() == {"username": USERNAME}


async def test_invalid_api_key_401(client: httpx.AsyncClient) -> None:
    await setup_account(client)
    await create_api_key(client)

    with_session = await client.get("/api/auth/me", headers={"X-Api-Key": "wrong"})
    client.cookies.clear()
    without_session = await client.get("/api/auth/me", headers={"X-Api-Key": "wrong"})

    assert with_session.status_code == 401
    assert without_session.status_code == 401


# --- AC7: Origin check ------------------------------------------------------------------


async def test_cookie_post_with_mismatched_origin_403(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    await setup_account(client)

    response = await client.post("/api/auth/api-key", headers={"Origin": "http://evil"})

    assert response.status_code == 403
    account = await _account(app)
    assert account is not None and account.api_key_hash is None


async def test_cookie_post_with_matching_origin_ok(client: httpx.AsyncClient) -> None:
    await setup_account(client)

    response = await client.post("/api/auth/api-key", headers={"Origin": "http://test"})

    assert response.status_code == 200


async def test_cookie_post_with_referer_only_ok(app: FastAPI) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post(
            "/api/auth/setup",
            json={"username": USERNAME, "password": PASSWORD},
            headers={"Origin": "http://test"},
        )

        response = await c.post("/api/auth/api-key", headers={"Referer": "http://test/settings"})

    assert response.status_code == 200


async def test_cookie_post_without_origin_403(app: FastAPI) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post(
            "/api/auth/setup",
            json={"username": USERNAME, "password": PASSWORD},
            headers={"Origin": "http://test"},
        )

        response = await c.post("/api/auth/api-key")
        read = await c.get("/api/auth/me")

    assert response.status_code == 403
    assert read.status_code == 200


async def test_api_key_post_without_origin_ok(app: FastAPI, client: httpx.AsyncClient) -> None:
    await setup_account(client)
    api_key = await create_api_key(client)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        response = await c.post("/api/auth/api-key", headers={"X-Api-Key": api_key})

    assert response.status_code == 200


async def test_public_post_with_session_cookie_checks_origin(client: httpx.AsyncClient) -> None:
    await setup_account(client)

    response = await client.post(
        "/api/auth/login",
        json={"username": USERNAME, "password": PASSWORD},
        headers={"Origin": "http://evil"},
    )

    assert response.status_code == 403


# --- AC8: logout ------------------------------------------------------------------------


async def test_logout_deletes_session(app: FastAPI, client: httpx.AsyncClient) -> None:
    await setup_account(client)
    old_cookie = client.cookies[COOKIE_NAME]

    response = await client.post("/api/auth/logout")

    assert response.status_code == 204
    assert (
        'fetcharr_session=""' in _set_cookie(response)
        or "max-age=0" in _set_cookie(response).lower()
    )
    assert await _sessions(app) == []
    client.cookies.set(COOKIE_NAME, old_cookie)
    assert (await client.get("/api/auth/me")).status_code == 401


# --- AC9: change password ---------------------------------------------------------------


async def test_change_password_wrong_current_400(app: FastAPI, client: httpx.AsyncClient) -> None:
    await setup_account(client)
    before = await _account(app)

    response = await client.post(
        "/api/auth/password",
        json={"current_password": "wrong password", "new_password": "a new password"},
    )

    assert response.status_code == 400
    after = await _account(app)
    assert before is not None and after is not None
    assert after.password_hash == before.password_hash


async def test_change_password_keeps_current_revokes_others(app: FastAPI) -> None:
    async with make_client(app) as current, make_client(app, ip="10.0.0.9") as other:
        await setup_account(current)
        assert (await login(other)).status_code == 200

        response = await current.post(
            "/api/auth/password",
            json={"current_password": PASSWORD, "new_password": "a new password"},
        )

        assert response.status_code == 204
        assert (await current.get("/api/auth/me")).status_code == 200
        assert (await other.get("/api/auth/me")).status_code == 401
        assert len(await _sessions(app)) == 1
        other.cookies.clear()
        assert (await login(other)).status_code == 401
        assert (await login(other, password="a new password")).status_code == 200


# --- AC10: API key regeneration ---------------------------------------------------------


async def test_regenerate_api_key_returns_once_stores_hash(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    await setup_account(client)

    first = await create_api_key(client)
    account = await _account(app)
    second = await create_api_key(client)
    me = await client.get("/api/auth/me")
    client.cookies.clear()

    assert account is not None
    assert account.api_key_hash == hash_token(first)
    assert first not in (account.api_key_hash or "")
    assert first != second
    assert first not in me.text and second not in me.text
    assert (await client.get("/api/auth/me", headers={"X-Api-Key": first})).status_code == 401
    assert (await client.get("/api/auth/me", headers={"X-Api-Key": second})).status_code == 200


# --- AC12: hashing never blocks the loop ------------------------------------------------


class _SlowHasher(PasswordHasher):
    """Blocks for 200 ms: the loop guard fails any test that runs this on the event loop."""

    def hash(self, password: str | bytes, *, salt: bytes | None = None) -> str:
        time.sleep(0.2)
        return super().hash(password, salt=salt)

    def verify(self, hash: str | bytes, password: str | bytes):
        time.sleep(0.2)
        return super().verify(hash, password)


async def test_setup_and_login_do_not_block_loop(
    monkeypatch: pytest.MonkeyPatch, client: httpx.AsyncClient
) -> None:
    monkeypatch.setattr(utils, "_hasher", _SlowHasher())

    await setup_account(client)
    client.cookies.clear()
    response = await login(client)

    assert response.status_code == 200


# --- AC15: sliding expiry ---------------------------------------------------------------


async def test_session_expiry_slides_at_most_hourly(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    await setup_account(client)
    session_id = client.cookies[COOKIE_NAME]
    stale = utcnow() + SESSION_LIFETIME - timedelta(hours=2)
    async with app.state.db.write_session() as session:
        await session.execute(
            update(AuthSession).where(AuthSession.id == session_id).values(expires_at=stale)
        )

    first = await client.get("/api/auth/me")
    [row] = await _sessions(app)
    second = await client.get("/api/auth/me")
    [row_again] = await _sessions(app)

    assert first.status_code == 200
    assert f"max-age={THIRTY_DAYS}" in _set_cookie(first).lower()
    assert row.expires_at > utcnow() + SESSION_LIFETIME - timedelta(minutes=1)
    assert second.status_code == 200
    assert "set-cookie" not in second.headers
    assert row_again.expires_at == row.expires_at


async def test_expired_session_401(app: FastAPI, client: httpx.AsyncClient) -> None:
    await setup_account(client)
    async with app.state.db.write_session() as session:
        await session.execute(
            update(AuthSession).values(expires_at=utcnow() - timedelta(seconds=1))
        )

    response = await client.get("/api/auth/me")

    assert response.status_code == 401
