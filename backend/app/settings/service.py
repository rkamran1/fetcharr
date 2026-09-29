"""The settings store: stored values, env precedence and secrets at rest (§7.5, §8, §10)."""

from dataclasses import asdict
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.session import Database
from app.integrations.arr import ArrConnection
from app.library.naming import (
    DEFAULT_TEMPLATES,
    TEMPLATE_KEYS,
    ColonMode,
    Templates,
    preview,
    unknown_tokens,
)
from app.settings.exceptions import InvalidSetting, YtdlpUpdateFailed
from app.settings.models import Setting
from app.settings.schemas import (
    NamingPreview,
    NamingPreviewRead,
    SettingsRead,
    SettingsUpdate,
    YtdlpUpdateRead,
)
from app.settings.utils import decrypt, encrypt
from app.transcode.profiles import DEFAULT_QUALITY, QUALITY_MAX, QUALITY_MIN
from app.ytdlp import runtime

RADARR_URL = "radarr_url"
RADARR_API_KEY = "radarr_api_key"
SONARR_URL = "sonarr_url"
SONARR_API_KEY = "sonarr_api_key"
TRANSCODE_QUALITY = "transcode_quality"
NAMING_TEMPLATES = "naming_templates"
COLON_MODE = "colon_mode"
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
        templates, colon = await self.naming()
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
            naming_templates=asdict(templates),
            colon_mode=colon,
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
                if key == NAMING_TEMPLATES:
                    # A PATCH of one template leaves the others alone, so the map is merged.
                    merged = {**await self._stored_templates(session), **_checked_templates(value)}
                    await self._store(session, key, merged, secret=False)
                    continue
                if key == COLON_MODE:
                    await self._store(session, key, _checked_colon(value), secret=False)
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

    async def naming(self) -> tuple[Templates, ColonMode]:
        """The templates and colon mode in force, falling back to §7.2's defaults."""
        async with self.db.read_session() as session:
            stored = await self._stored_templates(session)
            row = await session.get(Setting, COLON_MODE)
        colon = _checked_colon(row.value) if row is not None else ColonMode.SMART
        return Templates(**{**asdict(DEFAULT_TEMPLATES), **stored}), colon

    async def _stored_templates(self, session: AsyncSession) -> dict[str, str]:
        row = await session.get(Setting, NAMING_TEMPLATES)
        return row.value if row is not None and isinstance(row.value, dict) else {}

    async def preview_naming(self, body: NamingPreview) -> NamingPreviewRead:
        """Render an example per template for what the Settings form currently holds."""
        templates, colon = await self.naming()
        errors = {
            key: f"{', '.join(unknown_tokens(value))} is not a token"
            for key, value in (body.templates or {}).items()
            if key in TEMPLATE_KEYS and unknown_tokens(value)
        }
        usable = {
            key: value
            for key, value in (body.templates or {}).items()
            if key in TEMPLATE_KEYS and value and key not in errors
        }
        templates = Templates(**{**asdict(templates), **usable})
        colon = _checked_colon(body.colon_mode) if body.colon_mode else colon
        try:
            examples = preview(templates, colon)
        except ValueError as error:
            return NamingPreviewRead(examples={}, errors={**errors, "_": str(error)})
        return NamingPreviewRead(examples=examples, errors=errors)

    async def update_ytdlp(self) -> YtdlpUpdateRead:
        """Upgrade yt-dlp inside its own venv and report the versions around it (§13.1)."""
        try:
            result = await runtime.update_ytdlp()
        except runtime.UpdateError as error:
            raise YtdlpUpdateFailed(str(error)) from error
        return YtdlpUpdateRead(old=result.old, new=result.new, output=result.output)

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


def _checked_templates(value: object) -> dict[str, str]:
    """Only the §7.2 template names, only known tokens: these become paths on disk."""
    if not isinstance(value, dict):
        raise InvalidSetting("naming templates must be a map of template name to text")
    checked: dict[str, str] = {}
    for key, template in value.items():
        if key not in TEMPLATE_KEYS:
            raise InvalidSetting(f"{key!r} is not a naming template")
        if not isinstance(template, str) or not template.strip():
            raise InvalidSetting(f"the {key} template must not be empty")
        unknown = unknown_tokens(template)
        if unknown:
            raise InvalidSetting(f"{', '.join(unknown)} is not a token the {key} template can use")
        checked[key] = template.strip()
    return checked


def _checked_colon(value: object) -> ColonMode:
    try:
        return ColonMode(value)
    except ValueError as error:
        raise InvalidSetting(f"{value!r} is not a colon replacement mode") from error


def _connection(url: str | None, api_key: str | None) -> ArrConnection | None:
    if not url or not api_key:
        return None
    return ArrConnection(url=url, api_key=api_key)
