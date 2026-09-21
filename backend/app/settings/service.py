"""The settings store: stored values, env precedence and secrets at rest (§7.5, §8, §10)."""

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.session import Database
from app.integrations.arr import ArrConnection
from app.settings.exceptions import InvalidSetting
from app.settings.models import Setting
from app.settings.schemas import SettingsRead, SettingsUpdate
from app.settings.utils import decrypt, encrypt
from app.transcode.profiles import DEFAULT_QUALITY, QUALITY_MAX, QUALITY_MIN

RADARR_URL = "radarr_url"
RADARR_API_KEY = "radarr_api_key"
SONARR_URL = "sonarr_url"
SONARR_API_KEY = "sonarr_api_key"
TRANSCODE_QUALITY = "transcode_quality"
#: Which stored keys hold a Fernet token rather than a plain value.
SECRETS = frozenset({RADARR_API_KEY, SONARR_API_KEY})
#: Which stored keys have to look like a URL before they are worth saving.
URLS = frozenset({RADARR_URL, SONARR_URL})


class SettingsService:
    def __init__(self, db: Database, settings: Settings, secret_key: bytes) -> None:
        self.db = db
        self.settings = settings
        self.secret_key = secret_key

    async def read(self) -> SettingsRead:
        stored = await self._stored()
        radarr_url, radarr_key = self._radarr(stored)
        sonarr_url, sonarr_key = self._sonarr(stored)
        return SettingsRead(
            radarr_url=radarr_url,
            radarr_api_key_set=bool(radarr_key),
            radarr_from_env=bool(self.settings.radarr_url or self.settings.radarr_api_key),
            sonarr_url=sonarr_url,
            sonarr_api_key_set=bool(sonarr_key),
            sonarr_from_env=bool(self.settings.sonarr_url or self.settings.sonarr_api_key),
            transcode_quality=await self.transcode_quality(),
        )

    async def update(self, body: SettingsUpdate) -> SettingsRead:
        """Only the given fields change; an empty string removes one."""
        changes = body.model_dump(exclude_unset=True)
        async with self.db.write_session() as session:
            for key, value in changes.items():
                if value is None:
                    continue
                if not value:
                    await session.execute(delete(Setting).where(Setting.key == key))
                    continue
                if key == TRANSCODE_QUALITY:
                    # A PATCH of one profile leaves the others alone, so the map is merged.
                    merged = {**await self._stored_quality(session), **_checked_quality(value)}
                    await self._store(session, key, merged, secret=False)
                    continue
                if key in URLS and not value.startswith(("http://", "https://")):
                    raise InvalidSetting(f"{value!r} must start with http:// or https://")
                secret = key in SECRETS
                stored = encrypt(value, self.secret_key) if secret else value
                await self._store(session, key, stored, secret=secret)
        return await self.read()

    async def _store(self, session: AsyncSession, key: str, value: Any, *, secret: bool) -> None:
        row = await session.get(Setting, key)
        if row is None:
            session.add(Setting(key=key, value=value, is_secret=secret))
        else:
            row.value = value
            row.is_secret = secret

    async def transcode_quality(self) -> dict[str, int]:
        """The stored default per profile, falling back to §4.1's calibrated values."""
        async with self.db.read_session() as session:
            stored = await self._stored_quality(session)
        return {
            str(profile): int(stored.get(str(profile), default))
            for profile, default in DEFAULT_QUALITY.items()
        }

    async def _stored_quality(self, session: AsyncSession) -> dict[str, int]:
        row = await session.get(Setting, TRANSCODE_QUALITY)
        return row.value if row is not None and isinstance(row.value, dict) else {}

    async def radarr(self) -> ArrConnection | None:
        """The connection to use, or None when Radarr isn't configured (§7.5)."""
        return _connection(*self._radarr(await self._stored()))

    async def sonarr(self) -> ArrConnection | None:
        """The connection to use, or None when Sonarr isn't configured (§7.5)."""
        return _connection(*self._sonarr(await self._stored()))

    async def _stored(self) -> dict[str, str]:
        async with self.db.read_session() as session:
            rows = list(await session.scalars(select(Setting)))
        values = {}
        for row in rows:
            raw = str(row.value)
            value = decrypt(raw, self.secret_key) if row.is_secret else raw
            if value:
                values[row.key] = value
        return values

    def _radarr(self, stored: dict[str, str]) -> tuple[str | None, str | None]:
        """Env wins over the stored value (requirements §7.5)."""
        return (
            self.settings.radarr_url or stored.get(RADARR_URL),
            self.settings.radarr_api_key or stored.get(RADARR_API_KEY),
        )

    def _sonarr(self, stored: dict[str, str]) -> tuple[str | None, str | None]:
        return (
            self.settings.sonarr_url or stored.get(SONARR_URL),
            self.settings.sonarr_api_key or stored.get(SONARR_API_KEY),
        )


def _checked_quality(value: object) -> dict[str, int]:
    """Only the known profiles, only sane values: this ends up on an ffmpeg command line."""
    if not isinstance(value, dict):
        raise InvalidSetting("transcode quality must be a map of profile to number")
    known = {str(profile) for profile in DEFAULT_QUALITY}
    checked: dict[str, int] = {}
    for profile, quality in value.items():
        if profile not in known:
            raise InvalidSetting(f"{profile!r} is not a transcode profile")
        if not isinstance(quality, int) or isinstance(quality, bool):
            raise InvalidSetting(f"the quality for {profile} must be a whole number")
        if not QUALITY_MIN <= quality <= QUALITY_MAX:
            raise InvalidSetting(f"the quality for {profile} must be {QUALITY_MIN}-{QUALITY_MAX}")
        checked[profile] = quality
    return checked


def _connection(url: str | None, api_key: str | None) -> ArrConnection | None:
    if not url or not api_key:
        return None
    return ArrConnection(url=url, api_key=api_key)
