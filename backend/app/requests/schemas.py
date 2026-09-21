"""Request creation and path preview (requirements §5 step 2a/2b/2c/2d, §11)."""

from datetime import date, datetime
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, Field, model_validator

from app.jobs.constants import ImportStatus, JobStatus
from app.jobs.schemas import JobRead
from app.ytdlp.schemas import DownloadOptions

MediaType = Literal["other", "movie", "tv"]
#: `ask` is the safe default for a movie or an episode: the wizard resolves it first (§7.3).
CollisionPolicyName = Literal["ask", "replace", "keep_both"]
#: How a series numbers its episodes, from Sonarr's series type (§5 step 2b).
Numbering = Literal["standard", "daily"]


class MovieMedia(BaseModel):
    """Step 2a: what Radarr calls this movie, and which movie it is when it was picked."""

    radarr_movie_id: int | None = None
    title: Annotated[str, Field(min_length=1)]
    year: int | None = None


class TvMedia(BaseModel):
    """Step 2b: what Sonarr calls this series, and how it numbers its episodes."""

    sonarr_series_id: int | None = None
    title: Annotated[str, Field(min_length=1)]
    numbering: Numbering = "standard"


class EpisodeRef(BaseModel):
    """Which episode one video is, as picked from Sonarr (§5 step 2b, §10)."""

    season: int | None = None
    number: int | None = None
    sonarr_episode_id: int | None = None
    title: str = ""
    air_date: date | None = None


#: Which media block a request carries, decided by its `media_type` and nothing else.
MEDIA_MODELS: dict[str, type[MovieMedia] | type[TvMedia]] = {"movie": MovieMedia, "tv": TvMedia}


class RequestItem(BaseModel):
    """One video in a request; a TV item also says which episode it is."""

    inspection_id: int
    episode: EpisodeRef | None = None


class MediaDetails(BaseModel):
    """The half of a request that depends on the media type."""

    media_type: MediaType
    media: MovieMedia | TvMedia | None = None

    @model_validator(mode="before")
    @classmethod
    def _media_is_read_as_the_type_says(cls, data: Any) -> Any:
        """The media type picks the model; a plain union would let a series read as a movie."""
        if isinstance(data, dict) and isinstance(data.get("media"), dict):
            model = MEDIA_MODELS.get(str(data.get("media_type")))
            if model is not None:
                return {**data, "media": model.model_validate(data["media"])}
        return data

    @model_validator(mode="after")
    def _media_matches_the_type(self) -> Self:
        if self.media_type == "movie" and not isinstance(self.media, MovieMedia):
            raise ValueError("a movie request needs a media block with at least a title")
        if self.media_type == "tv" and not isinstance(self.media, TvMedia):
            raise ValueError("a tv request needs a media block with at least a series title")
        if self.media_type == "other" and self.media is not None:
            raise ValueError("an other request has no media details")
        return self


class CreateRequest(MediaDetails):
    items: Annotated[list[RequestItem], Field(min_length=1)]
    options: DownloadOptions
    collision_policy: CollisionPolicyName = "keep_both"
    #: Step 2's "Skip cookies" toggle: false runs without the site's cookies (§8).
    use_cookies: bool = True

    @model_validator(mode="after")
    def _items_match_the_type(self) -> Self:
        if self.media_type == "movie" and len(self.items) != 1:
            raise ValueError("a movie request is exactly one video")
        if self.media_type == "tv" and any(item.episode is None for item in self.items):
            raise ValueError("every episode in a tv request needs an episode block")
        return self


class CreatedRequest(BaseModel):
    id: str
    jobs: list[str]


class RequestRead(BaseModel):
    """A request with what "download again" needs to prefill its wizard (§12)."""

    id: str
    media_type: str
    title: str | None
    year: int | None
    numbering: str | None
    radarr_movie_id: int | None
    sonarr_series_id: int | None
    options: dict[str, Any]
    created_at: datetime
    jobs: list[JobRead]


#: The largest History page (§11).
MAX_PER_PAGE = 100


class RequestFilters(BaseModel):
    """`GET /api/requests`: History's filters, search and page (§11, §12)."""

    model_config = {"extra": "forbid", "populate_by_name": True}

    type: MediaType | None = None
    status: JobStatus | None = None
    import_status: ImportStatus | None = None
    site: str | None = None
    #: Inclusive UTC calendar days on the request's creation time.
    from_: date | None = Field(None, alias="from")
    to: date | None = None
    q: Annotated[str | None, Field(max_length=200)] = None
    page: Annotated[int, Field(ge=1)] = 1
    per_page: Annotated[int, Field(ge=1, le=MAX_PER_PAGE)] = 25


class RequestPage(BaseModel):
    items: list[RequestRead]
    total: int
    page: int
    per_page: int


class PreviewRequest(MediaDetails):
    inspection_id: int
    options: DownloadOptions
    #: A TV preview needs to know which episode, because the name is built from it (§7.2).
    episode: EpisodeRef | None = None

    @model_validator(mode="after")
    def _a_tv_preview_needs_an_episode(self) -> Self:
        if self.media_type == "tv" and self.episode is None:
            raise ValueError("a tv preview needs an episode block")
        return self


class PathPreview(BaseModel):
    path: str
    #: True when that exact file is already sitting in completed/ un-imported (§7.3).
    exists: bool
