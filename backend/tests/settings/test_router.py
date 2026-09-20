"""GET/PATCH /api/settings: secrets go in, never out (requirements §11, AC1)."""

import json
from pathlib import Path

import httpx
from fastapi import FastAPI
from sqlalchemy import select

from app.config import Settings
from app.main import create_app
from app.settings.models import Setting
from app.settings.utils import decrypt
from tests.conftest import (
    RADARR_API_KEY,
    RADARR_URL,
    configure_radarr,
    make_client,
    setup_account,
)


async def _rows(app: FastAPI) -> dict[str, Setting]:
    async with app.state.db.read_session() as session:
        return {row.key: row for row in await session.scalars(select(Setting))}


async def test_patch_stores_the_api_key_encrypted(app: FastAPI, client: httpx.AsyncClient) -> None:
    await setup_account(client)

    await configure_radarr(client)

    rows = await _rows(app)
    secret = rows["radarr_api_key"]
    assert secret.is_secret is True
    assert RADARR_API_KEY not in str(secret.value)
    assert decrypt(str(secret.value), app.state.secret_key) == RADARR_API_KEY
    assert (rows["radarr_url"].value, rows["radarr_url"].is_secret) == (RADARR_URL, False)


async def test_get_never_returns_the_api_key(client: httpx.AsyncClient) -> None:
    await setup_account(client)
    await configure_radarr(client)

    response = await client.get("/api/settings")

    assert response.status_code == 200
    assert response.json() == {
        "radarr_url": RADARR_URL,
        "radarr_api_key_set": True,
        "radarr_from_env": False,
    }
    assert RADARR_API_KEY not in json.dumps(response.json())


async def test_get_before_anything_is_configured(client: httpx.AsyncClient) -> None:
    await setup_account(client)

    response = await client.get("/api/settings")

    assert response.json() == {
        "radarr_url": None,
        "radarr_api_key_set": False,
        "radarr_from_env": False,
    }


async def test_env_values_override_stored_ones(settings: Settings, static_dir: Path) -> None:
    from_env = settings.model_copy(
        update={"radarr_url": "http://env-radarr:7878", "radarr_api_key": "env-key"}
    )
    application = create_app(from_env, static_dir=static_dir)

    async with (
        application.router.lifespan_context(application),
        make_client(application) as c,
    ):
        await setup_account(c)
        await configure_radarr(c)
        body = (await c.get("/api/settings")).json()

    assert body == {
        "radarr_url": "http://env-radarr:7878",
        "radarr_api_key_set": True,
        "radarr_from_env": True,
    }


async def test_patch_rejects_a_url_without_a_scheme(client: httpx.AsyncClient) -> None:
    await setup_account(client)

    response = await client.patch("/api/settings", json={"radarr_url": "radarr:7878"})

    assert response.status_code == 422
    assert "http://" in response.json()["detail"]


async def test_settings_require_a_session(client: httpx.AsyncClient) -> None:
    await setup_account(client)
    client.cookies.clear()

    assert (await client.get("/api/settings")).status_code == 401
    assert (await client.patch("/api/settings", json={"radarr_url": RADARR_URL})).status_code == 401
