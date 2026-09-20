from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow


class Request(Base):
    """One download request: the media details plus the options its jobs share (§10)."""

    __tablename__ = "requests"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    media_type: Mapped[str] = mapped_column(String)
    title: Mapped[str | None] = mapped_column(String)
    year: Mapped[int | None] = mapped_column(Integer)
    numbering: Mapped[str | None] = mapped_column(String)
    # Filled by M5b/M6, when a request can point at a Radarr movie or Sonarr series.
    radarr_movie_id: Mapped[int | None] = mapped_column(Integer)
    sonarr_series_id: Mapped[int | None] = mapped_column(Integer)
    options: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
