from pydantic import BaseModel


class PathCheckRead(BaseModel):
    path: str
    ok: bool
    error: str | None


class PathReportRead(BaseModel):
    ok: bool
    same_filesystem: bool
    checks: list[PathCheckRead]


class SystemStatus(BaseModel):
    version: str
    paths: PathReportRead
