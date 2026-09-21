from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow


class Site(Base):
    """A site is a key plus the domains whose URLs use its cookies (requirements §8, §10)."""

    __tablename__ = "sites"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    label: Mapped[str] = mapped_column(String)
    domains: Mapped[list[str]] = mapped_column(JSON)
    builtin: Mapped[bool] = mapped_column(Boolean, default=False)


class SiteCookies(Base):
    """One site's cookie file: ciphertext plus a plaintext summary, never the contents (§8)."""

    __tablename__ = "site_cookies"

    site_key: Mapped[str] = mapped_column(
        String, ForeignKey("sites.key", ondelete="CASCADE"), primary_key=True
    )
    enc_blob: Mapped[str] = mapped_column(String)
    cookie_count: Mapped[int] = mapped_column(Integer)
    earliest_expiry: Mapped[datetime | None] = mapped_column(DateTime)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime)
    flagged_invalid: Mapped[bool] = mapped_column(Boolean, default=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
