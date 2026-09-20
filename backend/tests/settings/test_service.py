"""Env precedence and the connection the import step uses (requirements §7.5, AC1)."""

from collections.abc import AsyncIterator

import pytest
from cryptography.fernet import Fernet

from app.config import Settings
from app.db.session import Database
from app.integrations.arr import ArrConnection
from app.settings.schemas import SettingsUpdate
from app.settings.service import SettingsService
from tests.conftest import RADARR_API_KEY, RADARR_URL, SONARR_API_KEY, SONARR_URL


@pytest.fixture
async def db(migrated_db_url: str) -> AsyncIterator[Database]:
    database = Database(migrated_db_url)
    try:
        yield database
    finally:
        await database.dispose()


def _service(db: Database, settings: Settings) -> SettingsService:
    return SettingsService(db, settings, Fernet.generate_key())


async def test_stored_values_become_the_connection(db: Database, settings: Settings) -> None:
    service = _service(db, settings)

    await service.update(SettingsUpdate(radarr_url=RADARR_URL, radarr_api_key=RADARR_API_KEY))

    assert await service.radarr() == ArrConnection(url=RADARR_URL, api_key=RADARR_API_KEY)


async def test_env_values_override_stored_ones(db: Database, settings: Settings) -> None:
    stored = _service(db, settings)
    await stored.update(SettingsUpdate(radarr_url=RADARR_URL, radarr_api_key=RADARR_API_KEY))
    from_env = _service(
        db,
        settings.model_copy(
            update={"radarr_url": "http://env-radarr:7878", "radarr_api_key": "env-key"}
        ),
    )

    read = await from_env.read()

    assert await from_env.radarr() == ArrConnection("http://env-radarr:7878", "env-key")
    assert read.radarr_url == "http://env-radarr:7878"
    assert read.radarr_from_env is True


async def test_a_half_configured_radarr_has_no_connection(db: Database, settings: Settings) -> None:
    service = _service(db, settings)

    await service.update(SettingsUpdate(radarr_url=RADARR_URL))

    assert await service.radarr() is None
    assert (await service.read()).radarr_api_key_set is False


async def test_an_empty_value_clears_the_setting(db: Database, settings: Settings) -> None:
    service = _service(db, settings)
    await service.update(SettingsUpdate(radarr_url=RADARR_URL, radarr_api_key=RADARR_API_KEY))

    await service.update(SettingsUpdate(radarr_api_key=""))

    read = await service.read()
    assert read.radarr_url == RADARR_URL
    assert read.radarr_api_key_set is False


async def test_the_sonarr_api_key_is_stored_encrypted(db: Database, settings: Settings) -> None:
    """AC1: the stored Sonarr values become a connection, and the key round-trips."""
    service = _service(db, settings)

    await service.update(SettingsUpdate(sonarr_url=SONARR_URL, sonarr_api_key=SONARR_API_KEY))

    assert await service.sonarr() == ArrConnection(url=SONARR_URL, api_key=SONARR_API_KEY)
    read = await service.read()
    assert (read.sonarr_url, read.sonarr_api_key_set) == (SONARR_URL, True)
    # A second service with another key can't read the token back (§8).
    other = _service(db, settings)
    assert await other.sonarr() is None


async def test_sonarr_env_values_win_over_stored_ones(db: Database, settings: Settings) -> None:
    """AC1: SONARR_URL/SONARR_API_KEY override Settings, exactly as Radarr's pair does."""
    stored = _service(db, settings)
    await stored.update(SettingsUpdate(sonarr_url=SONARR_URL, sonarr_api_key=SONARR_API_KEY))
    from_env = _service(
        db,
        settings.model_copy(
            update={"sonarr_url": "http://env-sonarr:8989", "sonarr_api_key": "env-key"}
        ),
    )

    read = await from_env.read()

    assert await from_env.sonarr() == ArrConnection("http://env-sonarr:8989", "env-key")
    assert read.sonarr_url == "http://env-sonarr:8989"
    assert read.sonarr_from_env is True
    # The two apps are configured independently.
    assert read.radarr_from_env is False


async def test_a_half_configured_sonarr_has_no_connection(db: Database, settings: Settings) -> None:
    service = _service(db, settings)

    await service.update(SettingsUpdate(sonarr_url=SONARR_URL))

    assert await service.sonarr() is None
    assert (await service.read()).sonarr_api_key_set is False
