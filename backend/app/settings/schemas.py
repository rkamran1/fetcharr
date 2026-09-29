"""The settings API shapes (requirements §11). A secret is reported as set or not set."""

from pydantic import BaseModel

from app.library.naming import ColonMode


class SettingsRead(BaseModel):
    radarr_url: str | None
    radarr_api_key_set: bool
    #: True when RADARR_URL/RADARR_API_KEY are set, so editing here would change nothing.
    radarr_from_env: bool
    sonarr_url: str | None
    sonarr_api_key_set: bool
    #: The same, for SONARR_URL/SONARR_API_KEY.
    sonarr_from_env: bool
    #: The default quality per transcode profile; the scales differ, so it is per profile.
    transcode_quality: dict[str, int]
    #: Every §7.2 template, stored ones over the defaults.
    naming_templates: dict[str, str]
    colon_mode: ColonMode


class SettingsUpdate(BaseModel):
    """Only the given fields change; an empty string clears one."""

    radarr_url: str | None = None
    radarr_api_key: str | None = None
    sonarr_url: str | None = None
    sonarr_api_key: str | None = None
    #: The whole map, or a subset of it; unknown profiles and out-of-range values are refused.
    transcode_quality: dict[str, int] | None = None
    #: A subset of the templates; an empty map resets every template to the §7.2 default.
    naming_templates: dict[str, str] | None = None
    colon_mode: ColonMode | None = None


class NamingPreview(BaseModel):
    """What the Settings form holds right now; anything missing falls back to the stored value."""

    templates: dict[str, str] | None = None
    colon_mode: ColonMode | None = None


class NamingPreviewRead(BaseModel):
    #: One example path per kind of target: movie, episode, specials, daily, other.
    examples: dict[str, str]
    #: Per template, why it could not be used for the examples.
    errors: dict[str, str]


class YtdlpUpdateRead(BaseModel):
    old: str | None
    new: str | None
    #: The tail of pip's output, so the UI can show what happened.
    output: str
