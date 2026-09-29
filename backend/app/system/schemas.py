from pydantic import BaseModel


class PathCheckRead(BaseModel):
    path: str
    ok: bool
    error: str | None


class PathReportRead(BaseModel):
    ok: bool
    same_filesystem: bool
    checks: list[PathCheckRead]


class ProfileCheckRead(BaseModel):
    """One hardware profile's one-second test encode (§13.1)."""

    profile: str
    ok: bool
    error: str | None


class TranscodeReportRead(BaseModel):
    """The /dev/dri + QSV/VAAPI check (requirements §11)."""

    device: bool
    device_path: str
    #: False until someone runs the full test; startup only looks at the render device.
    tested: bool
    hevc_encode: bool
    ok: bool
    message: str
    profiles: list[ProfileCheckRead]


class ToolsRead(BaseModel):
    """The binaries the downloads lean on; None means the tool isn't there (§11)."""

    ytdlp: str | None
    ffmpeg: str | None
    deno: str | None
    js_runtime: str | None
    aria2c: bool
    #: Whether the container upgrades yt-dlp before it starts (§13.1).
    update_on_start: bool


class DatabaseRead(BaseModel):
    path: str
    size_bytes: int | None
    #: The newest nightly backup, by name, or None before the first one (§3.1 rule 7).
    last_backup: str | None


class ConcurrencyRead(BaseModel):
    """Sized from the environment at startup, so the Status page shows them read-only."""

    downloads: int
    transcodes: int


class ArrStatusRead(BaseModel):
    configured: bool
    ok: bool
    version: str | None = None
    error: str | None = None


class SystemStatus(BaseModel):
    version: str
    tools: ToolsRead
    paths: PathReportRead
    transcode: TranscodeReportRead
    database: DatabaseRead
    concurrency: ConcurrencyRead
    radarr: ArrStatusRead
    sonarr: ArrStatusRead
