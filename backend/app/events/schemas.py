"""The SSE payloads (requirements §6, §11)."""

from typing import Any, Literal

from pydantic import BaseModel

EventType = Literal["job.progress", "job.state", "job.import", "job.log", "request.summary"]


class Event(BaseModel):
    """One server-sent event: `type` becomes the SSE event name, `data` its JSON body."""

    type: EventType
    data: dict[str, Any]


class ProgressSnapshot(BaseModel):
    """The live progress of one job, kept in memory and never polled from the DB (§3.1)."""

    job_id: str
    progress_pct: float | None = None
    downloaded_bytes: int | None = None
    total_bytes: int | None = None
    speed_bps: float | None = None
    eta_s: int | None = None
