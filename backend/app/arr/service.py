"""Reads from Radarr and Sonarr for the Settings tests and the pickers (§5, §7.5)."""

from collections.abc import Awaitable, Callable

import httpx

from app.arr.exceptions import (
    RadarrNotConfigured,
    RadarrUnavailable,
    SonarrNotConfigured,
    SonarrUnavailable,
)
from app.arr.schemas import (
    ArrTestResult,
    RadarrMovieList,
    RadarrMovieRead,
    SonarrEpisodeList,
    SonarrEpisodeRead,
    SonarrSeasonRead,
    SonarrSeriesList,
    SonarrSeriesRead,
)
from app.integrations.arr import (
    ArrConnection,
    ArrError,
    RadarrClient,
    RadarrMovie,
    SonarrClient,
    SonarrEpisode,
    SonarrSeries,
)
from app.settings.service import SettingsService

#: The pickers are typeaheads, not browsers: enough rows to choose from, never the library.
MOVIE_LIMIT = 20
SERIES_LIMIT = 20


class ArrService:
    def __init__(
        self, settings: SettingsService, radarr: RadarrClient, sonarr: SonarrClient
    ) -> None:
        self.settings = settings
        self.radarr = radarr
        self.sonarr = sonarr

    async def test(self) -> ArrTestResult:
        """Never raises: the Settings page wants the message, not an HTTP error."""
        return await _test(await self.settings.radarr(), self.radarr, "Radarr")

    async def test_sonarr(self) -> ArrTestResult:
        return await _test(await self.settings.sonarr(), self.sonarr, "Sonarr")

    async def movies(
        self, query: str = "", missing: bool = False, refresh: bool = False
    ) -> RadarrMovieList:
        """`missing` is what Radarr's Wanted view means: monitored, and still without a file.

        `refresh` skips the five-minute cache, for the picker's Refresh button.
        """
        connection = await self._radarr()
        movies = await _guarded(
            lambda: self.radarr.movies(connection, refresh=refresh),
            connection,
            RadarrUnavailable,
        )
        if missing:
            movies = [movie for movie in movies if movie.monitored and not movie.has_file]
        matches = _narrow(movies, query, lambda movie: movie.title)
        return RadarrMovieList(movies=[_read_movie(movie) for movie in matches[:MOVIE_LIMIT]])

    async def series(
        self, query: str = "", missing: bool = False, refresh: bool = False
    ) -> SonarrSeriesList:
        """Sonarr's own series list, cached for five minutes (§5 step 2b).

        `missing` means what the library lacks: a season Sonarr knows episodes for and has
        no files for. Deliberately **not** Sonarr's Wanted view, which counts only what is
        monitored — a series added unmonitored reports nothing wanted and is precisely the
        one a person came here to fill. `refresh` skips the cache, for the Refresh button.
        """
        connection = await self._sonarr()
        series = await _guarded(
            lambda: self.sonarr.series(connection, refresh=refresh), connection, SonarrUnavailable
        )
        if missing:
            series = [show for show in series if show.missing > 0]
        matches = _narrow(series, query, lambda show: show.title)
        return SonarrSeriesList(series=[_read_series(show) for show in matches[:SERIES_LIMIT]])

    async def episodes(self, series_id: int, season: int | None = None) -> SonarrEpisodeList:
        """One season's episodes, so the mapping table can name them the way Sonarr does."""
        connection = await self._sonarr()
        episodes = await _guarded(
            lambda: self.sonarr.episodes(connection, series_id, season),
            connection,
            SonarrUnavailable,
        )
        ordered = sorted(episodes, key=lambda episode: (episode.season, episode.number))
        return SonarrEpisodeList(episodes=[_read_episode(episode) for episode in ordered])

    async def _radarr(self) -> ArrConnection:
        connection = await self.settings.radarr()
        if connection is None:
            raise RadarrNotConfigured
        return connection

    async def _sonarr(self) -> ArrConnection:
        connection = await self.settings.sonarr()
        if connection is None:
            raise SonarrNotConfigured
        return connection


async def _test(
    connection: ArrConnection | None, client: RadarrClient | SonarrClient, app: str
) -> ArrTestResult:
    if connection is None:
        return ArrTestResult(ok=False, error=f"{app} is not configured in Settings")
    try:
        version = await client.system_status(connection)
    except ArrError as error:
        return ArrTestResult(ok=False, error=str(error))
    except httpx.HTTPError as error:
        return ArrTestResult(ok=False, error=f"{connection.url} is unreachable: {error}")
    return ArrTestResult(ok=True, version=version)


async def _guarded[T](
    call: Callable[[], Awaitable[T]],
    connection: ArrConnection,
    unavailable: type[RadarrUnavailable] | type[SonarrUnavailable],
) -> T:
    """One place where a library error becomes the 502 the router reports."""
    try:
        return await call()
    except ArrError as error:
        raise unavailable(str(error)) from error
    except httpx.HTTPError as error:
        raise unavailable(f"{connection.url} is unreachable: {error}") from error


def _narrow[T](items: list[T], query: str, title: Callable[[T], str]) -> list[T]:
    wanted = query.strip().casefold()
    return [item for item in items if wanted in title(item).casefold()]


def _read_movie(movie: RadarrMovie) -> RadarrMovieRead:
    return RadarrMovieRead(
        id=movie.id,
        title=movie.title,
        year=movie.year,
        monitored=movie.monitored,
        has_file=movie.has_file,
        quality=movie.quality,
        poster=movie.poster,
    )


def _read_series(series: SonarrSeries) -> SonarrSeriesRead:
    return SonarrSeriesRead(
        id=series.id,
        title=series.title,
        series_type=series.series_type,
        monitored=series.monitored,
        seasons=[
            SonarrSeasonRead(
                number=season.number,
                episode_file_count=season.episode_file_count,
                episode_count=season.episode_count,
                total_episode_count=season.total_episode_count,
            )
            for season in series.seasons
        ],
        poster=series.poster,
    )


def _read_episode(episode: SonarrEpisode) -> SonarrEpisodeRead:
    return SonarrEpisodeRead(
        id=episode.id,
        season=episode.season,
        number=episode.number,
        title=episode.title,
        air_date=episode.air_date,
        has_file=episode.has_file,
        quality=episode.quality,
    )
