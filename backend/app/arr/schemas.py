"""The Radarr- and Sonarr-facing API shapes (requirements §11)."""

from datetime import date

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
    monitored: bool
    has_file: bool
    quality: str | None
    poster: str | None


class RadarrMovieList(BaseModel):
    movies: list[RadarrMovieRead]


class SonarrSeasonRead(BaseModel):
    number: int
    episode_file_count: int
    #: Episodes that have aired and are monitored; the gap to the file count is "missing".
    episode_count: int
    total_episode_count: int


class SonarrSeriesRead(BaseModel):
    id: int
    title: str
    #: `standard` numbers by season and episode, `daily` by air date (§5 step 2b).
    series_type: str
    monitored: bool
    seasons: list[SonarrSeasonRead]
    poster: str | None


class SonarrSeriesList(BaseModel):
    series: list[SonarrSeriesRead]


class SonarrEpisodeRead(BaseModel):
    id: int
    season: int
    number: int
    title: str
    air_date: date | None
    has_file: bool
    quality: str | None


class SonarrEpisodeList(BaseModel):
    episodes: list[SonarrEpisodeRead]
