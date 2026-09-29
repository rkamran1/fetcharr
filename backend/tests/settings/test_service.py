"""Env precedence and the connection the import step uses (requirements §7.5, AC1)."""

from collections.abc import AsyncIterator
from dataclasses import asdict

import pytest
from cryptography.fernet import Fernet

from app.config import Settings
from app.db.session import Database
from app.integrations.arr import ArrConnection
from app.library.naming import DEFAULT_TEMPLATES, ColonMode
from app.settings.exceptions import InvalidSetting
from app.settings.models import Setting
from app.settings.schemas import NamingPreview, SettingsUpdate
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


async def test_naming_defaults_to_the_documented_templates(
    db: Database, settings: Settings
) -> None:
    assert await _service(db, settings).naming() == (DEFAULT_TEMPLATES, ColonMode.SMART)


async def test_naming_round_trip(db: Database, settings: Settings) -> None:
    service = _service(db, settings)

    await service.update(
        SettingsUpdate(naming_templates={"other": "{Title}"}, colon_mode=ColonMode.DASH)
    )

    templates, colon = await service.naming()
    assert (templates.other, colon) == ("{Title}", ColonMode.DASH)
    # The templates that weren't sent keep their default.
    assert templates.movie_file == DEFAULT_TEMPLATES.movie_file


async def test_unknown_token_raises_invalid_setting(db: Database, settings: Settings) -> None:
    service = _service(db, settings)

    with pytest.raises(InvalidSetting, match="{Episode}"):
        await service.update(SettingsUpdate(naming_templates={"standard_episode": "{Episode}"}))

    assert await service.naming() == (DEFAULT_TEMPLATES, ColonMode.SMART)


async def test_unknown_template_key_raises_invalid_setting(
    db: Database, settings: Settings
) -> None:
    with pytest.raises(InvalidSetting, match="nope"):
        await _service(db, settings).update(SettingsUpdate(naming_templates={"nope": "{Title}"}))


async def test_an_empty_template_is_refused(db: Database, settings: Settings) -> None:
    with pytest.raises(InvalidSetting, match="must not be empty"):
        await _service(db, settings).update(SettingsUpdate(naming_templates={"other": "  "}))


async def test_a_stored_colon_mode_that_is_not_one_is_refused(
    db: Database, settings: Settings
) -> None:
    """The schema refuses a bad mode at the API; this is the guard on what was stored."""
    async with db.write_session() as session:
        session.add(Setting(key="colon_mode", value="sideways", is_secret=False))

    with pytest.raises(InvalidSetting, match="colon replacement mode"):
        await _service(db, settings).naming()


async def test_empty_templates_reset_to_the_defaults(db: Database, settings: Settings) -> None:
    service = _service(db, settings)
    await service.update(SettingsUpdate(naming_templates={"other": "{Title}"}))

    read = await service.update(SettingsUpdate(naming_templates={}))

    assert read.naming_templates == asdict(DEFAULT_TEMPLATES)
    assert await service.naming() == (DEFAULT_TEMPLATES, ColonMode.SMART)


async def test_preview_uses_the_form_over_the_stored_templates(
    db: Database, settings: Settings
) -> None:
    service = _service(db, settings)
    await service.update(SettingsUpdate(naming_templates={"other": "{Title}"}))

    result = await service.preview_naming(NamingPreview(templates={"other": "{Id} {Title}"}))

    assert result.examples["other"] == "other/dQw4w9WgXcQ A Talk - Part One.mkv"
    assert result.errors == {}


async def test_preview_reports_an_unknown_token_instead_of_failing(
    db: Database, settings: Settings
) -> None:
    result = await _service(db, settings).preview_naming(
        NamingPreview(templates={"other": "{Nope}"})
    )

    assert result.errors["other"].startswith("{Nope}")
    # The other examples still render, from the stored templates.
    assert result.examples["movie"].startswith("movies/")


async def test_preview_follows_the_colon_mode(db: Database, settings: Settings) -> None:
    service = _service(db, settings)

    smart = await service.preview_naming(NamingPreview(colon_mode=ColonMode.SMART))
    deleted = await service.preview_naming(NamingPreview(colon_mode=ColonMode.DELETE))

    assert smart.examples["other"] != deleted.examples["other"]
    assert deleted.examples["other"] == "other/A Talk Part One [dQw4w9WgXcQ].mkv"
