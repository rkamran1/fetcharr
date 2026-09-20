from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow
from app.jobs.constants import ImportStatus, JobStatus
from app.library.organizer import CollisionPolicy


class Job(Base):
    """One download, checkpointed step by step (requirements §6, §6.1, §10)."""

    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_created_at", "created_at"),
        Index("ix_jobs_status", "status"),
        Index("ix_jobs_video_id", "video_id"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    request_id: Mapped[str] = mapped_column(
        String, ForeignKey("requests.id", ondelete="CASCADE"), index=True
    )

    # Source, from the inspection.
    url: Mapped[str] = mapped_column(String)
    extractor: Mapped[str | None] = mapped_column(String)
    video_id: Mapped[str | None] = mapped_column(String)
    # From the inspection: decides the fragment/aria2c defaults and the chunk-size flags (§4).
    stream_type: Mapped[str | None] = mapped_column(String)
    source_title: Mapped[str | None] = mapped_column(String)
    thumbnail_url: Mapped[str | None] = mapped_column(String)
    duration: Mapped[float | None] = mapped_column(Float)

    # Lifecycle.
    status: Mapped[str] = mapped_column(String, default=JobStatus.QUEUED)
    phase: Mapped[str | None] = mapped_column(String)
    last_completed_step: Mapped[str | None] = mapped_column(String)
    step_timings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=1)

    # Progress; written from the in-memory snapshot at most every ~2 s (§3.1 rule 5).
    progress_pct: Mapped[float | None] = mapped_column(Float)
    downloaded_bytes: Mapped[int | None] = mapped_column(Integer)
    total_bytes: Mapped[int | None] = mapped_column(Integer)
    speed_bps: Mapped[float | None] = mapped_column(Float)
    eta_s: Mapped[int | None] = mapped_column(Integer)

    # Files.
    job_dir: Mapped[str] = mapped_column(String)
    completed_path: Mapped[str | None] = mapped_column(String)
    sidecar_paths: Mapped[list[str]] = mapped_column(JSON, default=list)
    file_size: Mapped[int | None] = mapped_column(Integer)
    probed: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    # What to do when the destination is already taken; the wizard asks first (§7.3).
    collision_policy: Mapped[str] = mapped_column(String, default=CollisionPolicy.KEEP_BOTH)

    # The Radarr/Sonarr import (§7.5). A failed import never fails the job itself (§6).
    import_status: Mapped[str] = mapped_column(String, default=ImportStatus.NOT_APPLICABLE)
    import_command_id: Mapped[str | None] = mapped_column(String)
    import_attempts: Mapped[int] = mapped_column(Integer, default=0)
    import_detail: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    imported_path: Mapped[str | None] = mapped_column(String)
    imported_at: Mapped[datetime | None] = mapped_column(DateTime)
    error_code: Mapped[str | None] = mapped_column(String)
    error_message: Mapped[str | None] = mapped_column(String)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)


class JobLog(Base):
    """One line of a job's output, written in batches about once a second (§10)."""

    __tablename__ = "job_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[str] = mapped_column(
        String, ForeignKey("jobs.id", ondelete="CASCADE"), index=True
    )
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    level: Mapped[str] = mapped_column(String, default="info")
    line: Mapped[str] = mapped_column(String)
