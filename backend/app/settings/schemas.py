"""The settings API shapes (requirements §11). A secret is reported as set or not set."""

from pydantic import BaseModel


class SettingsRead(BaseModel):
    radarr_url: str | None
    radarr_api_key_set: bool
    #: True when RADARR_URL/RADARR_API_KEY are set, so editing here would change nothing.
    radarr_from_env: bool


class SettingsUpdate(BaseModel):
    """Only the given fields change; an empty string clears one."""

    radarr_url: str | None = None
    radarr_api_key: str | None = None
