"""Saved option bundles: CRUD, and the one-default-per-media-type rule (requirements §5)."""

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import Database
from app.presets.exceptions import PresetNotFound
from app.presets.models import Preset
from app.presets.schemas import PresetCreate, PresetRead, PresetUpdate


class PresetsService:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def read_all(self) -> list[PresetRead]:
        async with self.db.read_session() as session:
            presets = await session.scalars(select(Preset).order_by(Preset.media_type, Preset.name))
            return [_read(preset) for preset in presets]

    async def create(self, body: PresetCreate) -> PresetRead:
        async with self.db.write_session() as session:
            preset = Preset(
                name=body.name,
                media_type=body.media_type,
                options=body.options.model_dump(mode="json"),
                is_default=body.is_default,
            )
            session.add(preset)
            await session.flush()
            if body.is_default:
                await _clear_other_defaults(session, preset)
            return _read(preset)

    async def update(self, preset_id: int, body: PresetUpdate) -> PresetRead:
        async with self.db.write_session() as session:
            preset = await session.get(Preset, preset_id)
            if preset is None:
                raise PresetNotFound(preset_id)
            if body.name is not None:
                preset.name = body.name
            if body.media_type is not None:
                preset.media_type = body.media_type
            if body.options is not None:
                preset.options = body.options.model_dump(mode="json")
            if body.is_default is not None:
                preset.is_default = body.is_default
            await session.flush()
            if preset.is_default:
                await _clear_other_defaults(session, preset)
            return _read(preset)

    async def delete(self, preset_id: int) -> None:
        async with self.db.write_session() as session:
            preset = await session.get(Preset, preset_id)
            if preset is None:
                raise PresetNotFound(preset_id)
            await session.delete(preset)


async def _clear_other_defaults(session: AsyncSession, preset: Preset) -> None:
    """One default per media type: setting a new one unsets the old (§5 step 2d)."""
    await session.execute(
        update(Preset)
        .where(Preset.media_type == preset.media_type, Preset.id != preset.id)
        .values(is_default=False)
    )


def _read(preset: Preset) -> PresetRead:
    return PresetRead(
        id=preset.id,
        name=preset.name,
        media_type=preset.media_type,
        options=preset.options,
        is_default=preset.is_default,
    )
