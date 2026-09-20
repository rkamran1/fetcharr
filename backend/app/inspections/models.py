from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow


class Inspection(Base):
    """A cached `yt-dlp -J` result, normalised (requirements §5 step 1, §10)."""

    __tablename__ = "inspections"
    # Never reuse an id: a client may still hold one of an expired, deleted row.
    __table_args__ = {"sqlite_autoincrement": True}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    url: Mapped[str] = mapped_column(String, index=True)
    site_key: Mapped[str | None] = mapped_column(String)
    info: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
