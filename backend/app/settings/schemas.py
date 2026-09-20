"""The settings API shapes (requirements §11). A secret is reported as set or not set."""

from pydantic import BaseModel


class SettingsRead(BaseModel):
    radarr_url: str | None
    radarr_api_key_set: bool
    #: True when RADARR_URL/RADARR_API_KEY are set, so editing here would change nothing.
    radarr_from_env: bool
    sonarr_url: str | None
    sonarr_api_key_set: bool
    #: The same, for SONARR_URL/SONARR_API_KEY.
    sonarr_from_env: bool


class SettingsUpdate(BaseModel):
    """Only the given fields change; an empty string clears one."""

    radarr_url: str | None = None
    radarr_api_key: str | None = None
    sonarr_url: str | None = None
    sonarr_api_key: str | None = None
