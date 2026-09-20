"""Request creation and path preview (requirements §5 step 2c/2d, §11)."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from app.jobs.schemas import JobRead
from app.ytdlp.schemas import DownloadOptions


class RequestItem(BaseModel):
    """One video in a request; M6 adds the episode fields."""

    inspection_id: int


class CreateRequest(BaseModel):
    media_type: Literal["other"]
    items: Annotated[list[RequestItem], Field(min_length=1)]
    options: DownloadOptions


class CreatedRequest(BaseModel):
    id: str
    jobs: list[str]


class RequestRead(BaseModel):
    id: str
    media_type: str
    title: str | None
    created_at: datetime
    jobs: list[JobRead]


class PreviewRequest(BaseModel):
    media_type: Literal["other"]
    inspection_id: int
    options: DownloadOptions


class PathPreview(BaseModel):
    path: str
