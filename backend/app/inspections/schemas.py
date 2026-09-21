from datetime import datetime
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import AfterValidator, BaseModel, StringConstraints


def _check_url(url: str) -> str:
    if url.startswith("-"):
        raise ValueError("URL must not start with '-'")
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("Only http and https URLs are supported")
    return url


class InspectRequest(BaseModel):
    url: Annotated[str, StringConstraints(strip_whitespace=True), AfterValidator(_check_url)]


class AudioTrack(BaseModel):
    lang: str | None
    codec: str
    abr: int | None


class AutoSettings(BaseModel):
    fragments: int
    use_aria2c: bool


class PreviousDownload(BaseModel):
    """An earlier finished download of the same video: "already downloaded" (§10)."""

    job_id: str
    created_at: datetime
    media_type: str
    #: The library path once imported, else where fetcharr left it in completed/.
    path: str | None
    import_status: str


class InspectResult(BaseModel):
    inspection_id: int
    #: The site whose cookies apply to this URL, if any (§8).
    site_key: str | None
    title: str | None
    uploader: str | None
    thumbnail: str | None
    duration: float | None
    webpage_url: str | None
    extractor: str | None
    id: str | None
    upload_date: str | None
    release_year: int | None
    video_heights: list[int]
    video_codecs: list[str]
    audio_tracks: list[AudioTrack]
    has_hdr: bool
    subtitles: dict[str, list[str]]
    automatic_captions: dict[str, list[str]]
    estimated_sizes: dict[str, int]
    stream_type: Literal["hls", "dash", "http"]
    auto: AutoSettings
    #: Finished downloads with the same extractor and video id, newest first (§10).
    previous_downloads: list[PreviousDownload] = []
