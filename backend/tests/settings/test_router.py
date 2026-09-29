"""GET/PATCH /api/settings: secrets go in, never out (requirements §11, AC1)."""

import json
from dataclasses import asdict
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from app.config import Settings
from app.library.naming import DEFAULT_TEMPLATES
from app.main import create_app
from app.settings.models import Setting
from app.settings.utils import decrypt
from app.ytdlp import runtime
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

#: §4.1's calibrated starting points, before anyone changes them in Settings.
DEFAULT_TRANSCODE_QUALITY = {"hevc-qsv": 24, "hevc-vaapi": 24, "x265-software": 23}
#: The §7.2 templates as Settings reports them when nothing has been changed.
DEFAULT_NAMING = asdict(DEFAULT_TEMPLATES)


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
        "transcode_quality": DEFAULT_TRANSCODE_QUALITY,
        "naming_templates": DEFAULT_NAMING,
        "colon_mode": "smart",
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
        "transcode_quality": DEFAULT_TRANSCODE_QUALITY,
        "naming_templates": DEFAULT_NAMING,
        "colon_mode": "smart",
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
        "transcode_quality": DEFAULT_TRANSCODE_QUALITY,
        "naming_templates": DEFAULT_NAMING,
        "colon_mode": "smart",
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


# --------------------------------------------- the per-profile transcode quality (§4.1)


async def test_transcode_quality_starts_at_the_calibrated_defaults(
    client: httpx.AsyncClient,
) -> None:
    await setup_account(client)

    body = (await client.get("/api/settings")).json()

    assert body["transcode_quality"] == DEFAULT_TRANSCODE_QUALITY


async def test_patching_one_profile_leaves_the_others_alone(client: httpx.AsyncClient) -> None:
    await setup_account(client)

    first = await client.patch("/api/settings", json={"transcode_quality": {"hevc-qsv": 20}})
    second = await client.patch("/api/settings", json={"transcode_quality": {"x265-software": 26}})

    assert first.status_code == 200
    assert second.json()["transcode_quality"] == {
        "hevc-qsv": 20,
        "hevc-vaapi": 24,
        "x265-software": 26,
    }
    assert (await client.get("/api/settings")).json()["transcode_quality"]["hevc-qsv"] == 20


async def test_an_unknown_profile_or_a_silly_quality_is_rejected(
    client: httpx.AsyncClient,
) -> None:
    """The value ends up on an ffmpeg command line, so it is checked before it is stored."""
    await setup_account(client)

    unknown = await client.patch("/api/settings", json={"transcode_quality": {"av1-qsv": 24}})
    too_high = await client.patch("/api/settings", json={"transcode_quality": {"hevc-qsv": 99}})
    not_a_number = await client.patch(
        "/api/settings", json={"transcode_quality": {"hevc-qsv": "low"}}
    )

    assert unknown.status_code == 422
    assert "not a transcode profile" in unknown.json()["detail"]
    assert too_high.status_code == 422
    assert not_a_number.status_code == 422
    assert (await client.get("/api/settings")).json()["transcode_quality"] == (
        DEFAULT_TRANSCODE_QUALITY
    )


async def test_naming_update_with_unknown_token_is_422(client: httpx.AsyncClient) -> None:
    await setup_account(client)

    response = await client.patch(
        "/api/settings", json={"naming_templates": {"standard_episode": "{Episode}"}}
    )

    assert response.status_code == 422
    assert "{Episode}" in response.json()["detail"]


async def test_an_unknown_colon_mode_is_422(client: httpx.AsyncClient) -> None:
    await setup_account(client)

    assert (await client.patch("/api/settings", json={"colon_mode": "sideways"})).status_code == 422


async def test_naming_reset_restores_the_defaults(client: httpx.AsyncClient) -> None:
    await setup_account(client)
    changed = await client.patch("/api/settings", json={"naming_templates": {"other": "{Title}"}})
    assert changed.json()["naming_templates"]["other"] == "{Title}"

    reset = await client.patch("/api/settings", json={"naming_templates": {}})

    assert reset.json()["naming_templates"] == DEFAULT_NAMING
    assert reset.json()["colon_mode"] == "smart"


async def test_naming_preview_follows_the_colon_mode(client: httpx.AsyncClient) -> None:
    await setup_account(client)

    smart = await client.post("/api/settings/naming/preview", json={"colon_mode": "smart"})
    deleted = await client.post("/api/settings/naming/preview", json={"colon_mode": "delete"})

    assert smart.status_code == 200
    assert set(smart.json()["examples"]) == {"movie", "episode", "specials", "daily", "other"}
    assert smart.json()["examples"]["other"] != deleted.json()["examples"]["other"]


async def test_naming_preview_reports_an_unknown_token(client: httpx.AsyncClient) -> None:
    await setup_account(client)

    response = await client.post(
        "/api/settings/naming/preview", json={"templates": {"other": "{Nope}"}}
    )

    assert response.status_code == 200
    assert response.json()["errors"]["other"].startswith("{Nope}")


async def test_naming_preview_requires_session(client: httpx.AsyncClient) -> None:
    assert (await client.post("/api/settings/naming/preview", json={})).status_code == 401


async def test_ytdlp_update_returns_versions(client: httpx.AsyncClient, ytdlp_venv: Path) -> None:
    await setup_account(client)

    response = await client.post("/api/settings/yt-dlp/update")

    assert response.status_code == 200
    assert response.json() == {
        "old": "2026.09.01",
        "new": "2026.09.20",
        "output": "Successfully installed yt-dlp-2026.09.20",
    }


async def test_ytdlp_update_reports_a_failure_as_502(
    client: httpx.AsyncClient, ytdlp_venv: Path
) -> None:
    (ytdlp_venv / "bin" / "pip").write_text("#!/bin/sh\necho 'no network' >&2\nexit 1\n")
    (ytdlp_venv / "bin" / "pip").chmod(0o755)
    await setup_account(client)

    response = await client.post("/api/settings/yt-dlp/update")

    assert response.status_code == 502
    assert "no network" in response.json()["detail"]


async def test_ytdlp_update_requires_session(client: httpx.AsyncClient) -> None:
    assert (await client.post("/api/settings/yt-dlp/update")).status_code == 401


@pytest.fixture
def ytdlp_venv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A stand-in for /opt/yt-dlp whose pip "installs" a newer yt-dlp."""
    root = tmp_path / "opt" / "yt-dlp"
    (root / "bin").mkdir(parents=True)
    marker = root / "installed"
    for name, body in (
        ("pip", f"touch {marker}\necho 'Successfully installed yt-dlp-2026.09.20'"),
        ("yt-dlp", f"if [ -f {marker} ]; then echo 2026.09.20; else echo 2026.09.01; fi"),
    ):
        exe = root / "bin" / name
        exe.write_text(f"#!/bin/sh\n{body}\n")
        exe.chmod(0o755)
    monkeypatch.setattr(runtime, "YTDLP_PIP", root / "bin" / "pip")
    monkeypatch.setattr(runtime, "YTDLP_BIN", root / "bin" / "yt-dlp")
    return root
