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


class SystemStatus(BaseModel):
    version: str
    paths: PathReportRead
    transcode: TranscodeReportRead
