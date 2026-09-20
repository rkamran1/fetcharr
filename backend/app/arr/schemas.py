"""The Radarr-facing API shapes (requirements §11)."""

from pydantic import BaseModel


class ArrTestResult(BaseModel):
    """The Settings Test button: the version, or the reason it didn't work."""

    ok: bool
    version: str | None = None
    error: str | None = None


class RadarrMovieRead(BaseModel):
    id: int
    title: str
    year: int | None
    has_file: bool
    quality: str | None


class RadarrMovieList(BaseModel):
    movies: list[RadarrMovieRead]
