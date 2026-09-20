"""The settings store: stored values, env precedence and secrets at rest (§7.5, §8, §10)."""

from sqlalchemy import delete, select

from app.config import Settings
from app.db.session import Database
from app.integrations.arr import ArrConnection
from app.settings.exceptions import InvalidSetting
from app.settings.models import Setting
from app.settings.schemas import SettingsRead, SettingsUpdate
from app.settings.utils import decrypt, encrypt

RADARR_URL = "radarr_url"
RADARR_API_KEY = "radarr_api_key"
#: Which stored keys hold a Fernet token rather than a plain value.
SECRETS = frozenset({RADARR_API_KEY})


class SettingsService:
    def __init__(self, db: Database, settings: Settings, secret_key: bytes) -> None:
        self.db = db
        self.settings = settings
        self.secret_key = secret_key

    async def read(self) -> SettingsRead:
        stored = await self._stored()
        url, api_key = self._effective(stored)
        return SettingsRead(
            radarr_url=url,
            radarr_api_key_set=bool(api_key),
            radarr_from_env=bool(self.settings.radarr_url or self.settings.radarr_api_key),
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
                if key == RADARR_URL and not value.startswith(("http://", "https://")):
                    raise InvalidSetting(f"{value!r} must start with http:// or https://")
                secret = key in SECRETS
                stored = encrypt(value, self.secret_key) if secret else value
                row = await session.get(Setting, key)
                if row is None:
                    session.add(Setting(key=key, value=stored, is_secret=secret))
                else:
                    row.value = stored
                    row.is_secret = secret
        return await self.read()

    async def radarr(self) -> ArrConnection | None:
        """The connection to use, or None when Radarr isn't configured (§7.5)."""
        url, api_key = self._effective(await self._stored())
        if not url or not api_key:
            return None
        return ArrConnection(url=url, api_key=api_key)

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

    def _effective(self, stored: dict[str, str]) -> tuple[str | None, str | None]:
        """Env wins over the stored value (requirements §7.5)."""
        return (
            self.settings.radarr_url or stored.get(RADARR_URL),
            self.settings.radarr_api_key or stored.get(RADARR_API_KEY),
        )
