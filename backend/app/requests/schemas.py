"""Request creation and path preview (requirements §5 step 2a/2c/2d, §11)."""

from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, Field, model_validator

from app.jobs.schemas import JobRead
from app.ytdlp.schemas import DownloadOptions

MediaType = Literal["other", "movie"]
#: `ask` is the safe default for a movie: the wizard resolves it before submitting (§7.3).
CollisionPolicyName = Literal["ask", "replace", "keep_both"]


class MovieMedia(BaseModel):
    """Step 2a: what Radarr calls this movie, and which movie it is when it was picked."""

    radarr_movie_id: int | None = None
    title: Annotated[str, Field(min_length=1)]
    year: int | None = None


class RequestItem(BaseModel):
    """One video in a request; M6 adds the episode fields."""

    inspection_id: int


class MediaDetails(BaseModel):
    """The half of a request that depends on the media type."""

    media_type: MediaType
    media: MovieMedia | None = None

    @model_validator(mode="after")
    def _media_matches_the_type(self) -> Self:
        if self.media_type == "movie" and self.media is None:
            raise ValueError("a movie request needs a media block with at least a title")
        if self.media_type == "other" and self.media is not None:
            raise ValueError("an other request has no media details")
        return self


class CreateRequest(MediaDetails):
    items: Annotated[list[RequestItem], Field(min_length=1)]
    options: DownloadOptions
    collision_policy: CollisionPolicyName = "keep_both"

    @model_validator(mode="after")
    def _one_video_per_movie(self) -> Self:
        if self.media_type == "movie" and len(self.items) != 1:
            raise ValueError("a movie request is exactly one video")
        return self


class CreatedRequest(BaseModel):
    id: str
    jobs: list[str]


class RequestRead(BaseModel):
    id: str
    media_type: str
    title: str | None
    created_at: datetime
    jobs: list[JobRead]


class PreviewRequest(MediaDetails):
    inspection_id: int
    options: DownloadOptions


class PathPreview(BaseModel):
    path: str
    #: True when that exact file is already sitting in completed/ un-imported (§7.3).
    exists: bool
