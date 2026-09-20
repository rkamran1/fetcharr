"""Reads from Radarr for the Settings test and the movie picker (§5 step 2a, §7.5)."""

import httpx

from app.arr.exceptions import RadarrNotConfigured, RadarrUnavailable
from app.arr.schemas import ArrTestResult, RadarrMovieList, RadarrMovieRead
from app.integrations.arr import ArrError, RadarrClient, RadarrMovie
from app.settings.service import SettingsService

#: The picker is a typeahead, not a browser: enough rows to choose from, never the library.
MOVIE_LIMIT = 20


class ArrService:
    def __init__(self, settings: SettingsService, client: RadarrClient) -> None:
        self.settings = settings
        self.client = client

    async def test(self) -> ArrTestResult:
        """Never raises: the Settings page wants the message, not an HTTP error."""
        connection = await self.settings.radarr()
        if connection is None:
            return ArrTestResult(ok=False, error="Radarr is not configured in Settings")
        try:
            version = await self.client.system_status(connection)
        except ArrError as error:
            return ArrTestResult(ok=False, error=str(error))
        except httpx.HTTPError as error:
            return ArrTestResult(ok=False, error=f"{connection.url} is unreachable: {error}")
        return ArrTestResult(ok=True, version=version)

    async def movies(
        self, query: str = "", missing: bool = False, refresh: bool = False
    ) -> RadarrMovieList:
        """`missing` is what Radarr's Wanted view means: monitored, and still without a file.

        `refresh` skips the five-minute cache, for the picker's Refresh button.
        """
        connection = await self.settings.radarr()
        if connection is None:
            raise RadarrNotConfigured
        try:
            movies = await self.client.movies(connection, refresh=refresh)
        except ArrError as error:
            raise RadarrUnavailable(str(error)) from error
        except httpx.HTTPError as error:
            raise RadarrUnavailable(f"{connection.url} is unreachable: {error}") from error
        if missing:
            movies = [movie for movie in movies if movie.monitored and not movie.has_file]
        wanted = query.strip().casefold()
        matches = [movie for movie in movies if wanted in movie.title.casefold()]
        return RadarrMovieList(movies=[_read(movie) for movie in matches[:MOVIE_LIMIT]])


def _read(movie: RadarrMovie) -> RadarrMovieRead:
    return RadarrMovieRead(
        id=movie.id,
        title=movie.title,
        year=movie.year,
        monitored=movie.monitored,
        has_file=movie.has_file,
        quality=movie.quality,
        poster=movie.poster,
    )
