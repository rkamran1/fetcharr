from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_version: str = "dev"
    database_url: str = "sqlite+aiosqlite:////config/fetcharr.db"
    # Browsers drop Secure cookies over plain HTTP, which is common on a LAN (requirements §9).
    cookie_secure: bool = False
    # Both live on the /web-downloads volume, which Radarr/Sonarr must mount at the same path.
    completed_dir: Path = Path("/web-downloads/completed")
    incomplete_dir: Path = Path("/web-downloads/incomplete")
