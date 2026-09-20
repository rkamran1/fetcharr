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
    SONARR_API_KEY,
    SONARR_URL,
    configure_radarr,
    configure_sonarr,
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
        "sonarr_url": None,
        "sonarr_api_key_set": False,
        "sonarr_from_env": False,
    }
    assert RADARR_API_KEY not in json.dumps(response.json())


async def test_get_before_anything_is_configured(client: httpx.AsyncClient) -> None:
    await setup_account(client)

    response = await client.get("/api/settings")

    assert response.json() == {
        "radarr_url": None,
        "radarr_api_key_set": False,
        "radarr_from_env": False,
        "sonarr_url": None,
        "sonarr_api_key_set": False,
        "sonarr_from_env": False,
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
        "sonarr_url": None,
        "sonarr_api_key_set": False,
        "sonarr_from_env": False,
    }


async def test_sonarr_settings_are_saved_and_the_key_never_comes_back(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    """AC1: the Sonarr key is a Fernet token at rest, and only ever reported as set."""
    await setup_account(client)

    await configure_sonarr(client)

    rows = await _rows(app)
    secret = rows["sonarr_api_key"]
    assert secret.is_secret is True
    assert SONARR_API_KEY not in str(secret.value)
    assert decrypt(str(secret.value), app.state.secret_key) == SONARR_API_KEY
    assert (rows["sonarr_url"].value, rows["sonarr_url"].is_secret) == (SONARR_URL, False)

    body = (await client.get("/api/settings")).json()
    assert body["sonarr_url"] == SONARR_URL
    assert body["sonarr_api_key_set"] is True
    assert body["sonarr_from_env"] is False
    assert SONARR_API_KEY not in json.dumps(body)


async def test_sonarr_env_values_override_stored_ones(settings: Settings, static_dir: Path) -> None:
    """AC1: SONARR_URL/SONARR_API_KEY win, and the UI is told editing would do nothing."""
    from_env = settings.model_copy(
        update={"sonarr_url": "http://env-sonarr:8989", "sonarr_api_key": "env-key"}
    )
    application = create_app(from_env, static_dir=static_dir)

    async with (
        application.router.lifespan_context(application),
        make_client(application) as c,
    ):
        await setup_account(c)
        await configure_sonarr(c)
        body = (await c.get("/api/settings")).json()

    assert body["sonarr_url"] == "http://env-sonarr:8989"
    assert body["sonarr_api_key_set"] is True
    assert body["sonarr_from_env"] is True
    # The Radarr half is untouched by the Sonarr environment.
    assert body["radarr_from_env"] is False


async def test_a_sonarr_url_without_a_scheme_is_rejected(client: httpx.AsyncClient) -> None:
    """AC1: the same guard the Radarr URL has, or the failure surfaces much later."""
    await setup_account(client)

    response = await client.patch("/api/settings", json={"sonarr_url": "sonarr:8989"})

    assert response.status_code == 422
    assert "http://" in response.json()["detail"]


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
