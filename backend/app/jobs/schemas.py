"""The job API shapes (requirements §11)."""

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel


class JobRead(BaseModel):
    id: str
    request_id: str
    #: The request this job belongs to, so the queue can group and name it (§12).
    media_type: str
    request_title: str | None
    url: str
    source_title: str | None
    thumbnail_url: str | None
    duration: float | None
    status: str
    phase: str | None
    attempt: int
    progress_pct: float | None
    downloaded_bytes: int | None
    total_bytes: int | None
    speed_bps: float | None
    eta_s: int | None
    completed_path: str | None
    file_size: int | None
    #: True when a hardware transcode failed and x265-software finished it (§6.1).
    transcode_fallback_used: bool
    #: Which site's cookies it used (§8); History filters on it (§12).
    site_key: str | None
    #: When History's "delete file" removed the file; the row itself stays (§12).
    file_deleted_at: datetime | None
    # Which episode this is (tv only, §10).
    season: int | None
    episode: int | None
    episode_title: str | None
    air_date: date | None
    sonarr_episode_id: int | None
    import_status: str
    import_attempts: int
    import_detail: dict[str, Any] | None
    imported_path: str | None
    imported_at: datetime | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class JobList(BaseModel):
    jobs: list[JobRead]


class LogLine(BaseModel):
    ts: datetime
    level: str
    line: str


class JobLogRead(BaseModel):
    lines: list[LogLine]
