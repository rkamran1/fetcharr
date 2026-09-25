from sqlalchemy import JSON, Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Preset(Base):
    """A saved bundle of download options, with one default per media type (§10, §11)."""

    __tablename__ = "presets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    #: `movie`, `tv`, `other` or `any`; `any` presets are offered in every wizard.
    media_type: Mapped[str] = mapped_column(String)
    options: Mapped[dict] = mapped_column(JSON)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
