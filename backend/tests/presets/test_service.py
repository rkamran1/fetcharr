"""AC7: one default per media type, however often the default moves."""

from collections.abc import AsyncIterator

import pytest

from app.db.session import Database
from app.presets.schemas import PresetCreate, PresetMediaType, PresetUpdate
from app.presets.service import PresetsService
from app.ytdlp.schemas import DownloadOptions

OPTIONS = DownloadOptions(quality="1080p")


@pytest.fixture
async def db(migrated_db_url: str) -> AsyncIterator[Database]:
    database = Database(migrated_db_url)
    try:
        yield database
    finally:
        await database.dispose()


def _service(db: Database) -> PresetsService:
    return PresetsService(db)


async def _add(
    service: PresetsService, name: str, media_type: PresetMediaType, *, default: bool = False
) -> int:
    preset = await service.create(
        PresetCreate(name=name, media_type=media_type, options=OPTIONS, is_default=default)
    )
    return preset.id


async def _defaults(service: PresetsService, media_type: str) -> list[str]:
    return [p.name for p in await service.read_all() if p.media_type == media_type and p.is_default]


async def test_setting_a_default_unsets_the_previous_one_for_that_media_type(
    db: Database,
) -> None:
    service = _service(db)
    first = await _add(service, "first", "movie", default=True)
    second = await _add(service, "second", "movie")
    third = await _add(service, "third", "movie")

    await service.update(second, PresetUpdate(is_default=True))
    await service.update(third, PresetUpdate(is_default=True))
    await service.update(first, PresetUpdate(is_default=True))

    assert await _defaults(service, "movie") == ["first"]


async def test_creating_a_default_unsets_the_previous_one(db: Database) -> None:
    service = _service(db)
    await _add(service, "first", "tv", default=True)
    await _add(service, "second", "tv", default=True)

    assert await _defaults(service, "tv") == ["second"]


async def test_each_media_type_keeps_its_own_default(db: Database) -> None:
    service = _service(db)
    media_types: tuple[PresetMediaType, ...] = ("movie", "tv", "other", "any")
    for media_type in media_types:
        await _add(service, f"{media_type}-default", media_type, default=True)

    await _add(service, "another-movie", "movie", default=True)

    assert await _defaults(service, "movie") == ["another-movie"]
    assert await _defaults(service, "tv") == ["tv-default"]
    assert await _defaults(service, "other") == ["other-default"]
    assert await _defaults(service, "any") == ["any-default"]


async def test_options_round_trip_through_the_store(db: Database) -> None:
    service = _service(db)
    options = DownloadOptions.model_validate(
        {
            "quality": "720p",
            "container": "mp4",
            "subtitles": {"mode": "sidecar", "languages": ["en", "de"]},
            "sponsorblock": {"mode": "remove"},
            "rate_limit": "5M",
        }
    )
    preset = await service.create(
        PresetCreate(name="subs", media_type="any", options=options, is_default=False)
    )

    stored = next(p for p in await service.read_all() if p.id == preset.id)

    assert DownloadOptions.model_validate(stored.options) == options


async def test_delete_removes_the_row(db: Database) -> None:
    service = _service(db)
    preset_id = await _add(service, "gone", "other")

    await service.delete(preset_id)

    assert await service.read_all() == []
