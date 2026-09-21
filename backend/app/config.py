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
    # The download slot; held only during the download step (requirements §6.1).
    max_concurrent_downloads: int = 2
    # The transcode slot; held only during the transcode step, so downloads keep flowing.
    max_concurrent_transcodes: int = 1
    # Which libva driver ffmpeg loads for QSV/VAAPI; iHD is the Intel one (§13.1).
    libva_driver_name: str = "iHD"
    # Resume interrupted jobs from their checkpoint on boot; false fails them instead.
    auto_resume: bool = True
    # The Fernet key for secrets at rest (§8). Set it, or let the file below be generated.
    secret_key: str | None = None
    secret_key_file: Path = Path("/config/secret.key")
    # Set here, these win over whatever Settings holds (requirements §7.5).
    radarr_url: str | None = None
    radarr_api_key: str | None = None
    sonarr_url: str | None = None
    sonarr_api_key: str | None = None
