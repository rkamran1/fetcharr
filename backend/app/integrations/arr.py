"""Radarr's and Sonarr's v3 APIs: one shared client per app, the cached lookups and the
import command (§7.5).

A library module: no FastAPI, no database, no domain imports. Everything that decides what
to do with an answer (retry, checkpoint, verify) lives in the jobs pipeline; this module
only speaks HTTP and maps status codes onto the error types the retry policy names.

Both apps share a transport, a command API and an import lock, so ``_ArrClient`` holds
everything that is the same and each subclass adds only its own lookups.
"""

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx
from tenacity import wait_chain, wait_fixed

#: The library lists are big and change rarely; the pickers re-read them at most this often.
MOVIE_CACHE_TTL_S = 300.0
SERIES_CACHE_TTL_S = 300.0
CONNECT_TIMEOUT_S = 5.0
READ_TIMEOUT_S = 30.0

#: The import retry schedule from requirements §6.1: 10 s, 60 s, 300 s over four attempts.
IMPORT_WAIT = wait_chain(wait_fixed(10), wait_fixed(60), wait_fixed(300))
IMPORT_ATTEMPTS = 4
POLL_INTERVAL_S = 2.0
COMMAND_TIMEOUT_S = 600.0

MOVIE_SCAN = "DownloadedMoviesScan"
EPISODE_SCAN = "DownloadedEpisodesScan"
IMPORT_MODE = "Move"
#: Radarr/Sonarr report these when a command is done; anything else means keep polling.
FINISHED = ("completed", "failed", "aborted")

RADARR = "Radarr"
SONARR = "Sonarr"


class ArrError(Exception):
    """The arr app could not be asked, or answered with an error."""


class ArrAuthError(ArrError):
    """401/403: the API key is wrong. Never retried (requirements §6.1)."""


class ArrClientError(ArrError):
    """Another 4xx: the request itself is wrong, so retrying changes nothing."""


class ArrServerError(ArrError):
    """5xx: the arr app is unwell right now, so this one is retried."""


class ArrTimeout(ArrError):
    """The command never finished inside the timeout."""


@dataclass(frozen=True)
class ArrConnection:
    url: str
    api_key: str


@dataclass(frozen=True)
class ImportPolicy:
    """The knobs of the import step; injectable so tests never sleep (requirements §6.1)."""

    wait: Any = IMPORT_WAIT
    attempts: int = IMPORT_ATTEMPTS
    poll_interval: float = POLL_INTERVAL_S
    command_timeout: float = COMMAND_TIMEOUT_S


@dataclass(frozen=True)
class RadarrMovie:
    id: int
    title: str
    year: int | None
    #: Radarr only wants a file for the movies it monitors, so "missing" starts here (§5 2a).
    monitored: bool
    has_file: bool
    quality: str | None
    #: Radarr's poster, so a list of titles reads as a list of films.
    poster: str | None


@dataclass(frozen=True)
class SonarrSeason:
    number: int
    episode_file_count: int
    #: Sonarr's count of episodes that have **aired and are monitored**. Not what decides
    #: "missing": Sonarr reports 0 here for a series nobody is monitoring, which is exactly
    #: the series a person wants to fill by hand (M6 review, against Sonarr 4.0.20).
    episode_count: int
    total_episode_count: int

    @property
    def missing(self) -> int:
        """Episodes Sonarr knows about and has no file for, monitored or not (§5 step 2b)."""
        return max(self.total_episode_count - self.episode_file_count, 0)


@dataclass(frozen=True)
class SonarrSeries:
    id: int
    title: str
    #: `standard` numbers by season and episode, `daily` by air date (§5 step 2b).
    series_type: str
    #: Sonarr only hunts for what it monitors, so an unmonitored series is one it will
    #: never fill on its own. Shown as a hint, never used to hide anything.
    monitored: bool
    seasons: tuple[SonarrSeason, ...]
    #: Sonarr's poster, so the series picker reads as a list of shows.
    poster: str | None

    @property
    def missing(self) -> int:
        """How many aired, monitored episodes Sonarr has no file for (§5 step 2b)."""
        return sum(season.missing for season in self.seasons)


@dataclass(frozen=True)
class SonarrEpisode:
    id: int
    season: int
    number: int
    title: str
    air_date: date | None
    has_file: bool
    quality: str | None


class _ArrClient:
    """Long-lived: one connection pool and one import lock per arr app (§6.1)."""

    def __init__(
        self,
        app: str,
        *,
        client: httpx.AsyncClient | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.app = app
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(READ_TIMEOUT_S, connect=CONNECT_TIMEOUT_S)
        )
        self.clock = clock
        #: Import commands to one arr app run one at a time (requirements §6.1).
        self.import_lock = asyncio.Lock()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def system_status(self, connection: ArrConnection) -> str:
        """The app's version, which doubles as the connection test (§7.5)."""
        body = await self._get(connection, "system/status")
        return str(body.get("version") or "unknown")

    async def send_command(self, connection: ArrConnection, name: str, path: str) -> str:
        """The downloaded-scan command with `importMode: Move`, and its id back (§7.5)."""
        body = await self._post(
            connection, "command", {"name": name, "path": path, "importMode": IMPORT_MODE}
        )
        return str(body.get("id", "")) if isinstance(body, dict) else ""

    async def command(self, connection: ArrConnection, command_id: str) -> str:
        """The command's status: `queued`, `started`, `completed`, `failed` or `aborted`."""
        body = await self._get(connection, f"command/{command_id}")
        return str(body.get("status", "")) if isinstance(body, dict) else ""

    async def rejections(self, connection: ArrConnection, folder: str) -> list[str]:
        """Why the app left the files where they are, verbatim and de-duplicated (§7.5)."""
        body = await self._get(connection, "manualimport", params={"folder": folder})
        if not isinstance(body, list):
            return []
        reasons: list[str] = []
        for item in body:
            for rejection in (item or {}).get("rejections") or []:
                reason = rejection if isinstance(rejection, str) else rejection.get("reason")
                if reason and reason not in reasons:
                    reasons.append(str(reason))
        return reasons

    # ------------------------------------------------------------------ transport

    async def _get(
        self, connection: ArrConnection, path: str, params: dict[str, str] | None = None
    ) -> Any:
        response = await self._client.get(
            _url(connection, path), headers=_headers(connection), params=params
        )
        return self._body(response)

    async def _post(self, connection: ArrConnection, path: str, json: dict[str, Any]) -> Any:
        response = await self._client.post(
            _url(connection, path), headers=_headers(connection), json=json
        )
        return self._body(response)

    def _body(self, response: httpx.Response) -> Any:
        """One place where a status code becomes the exception type the retry policy names."""
        status = response.status_code
        if status in (401, 403):
            raise ArrAuthError(f"{self.app} rejected the API key; check it in Settings")
        if status >= 500:
            raise ArrServerError(f"{self.app} answered {status}")
        if status >= 400:
            raise ArrClientError(f"{self.app} answered {status}: {response.text[:200]}")
        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError as error:
            raise ArrClientError(f"{self.app} sent a body that isn't JSON: {error}") from error


class RadarrClient(_ArrClient):
    """Radarr, plus the movie cache the picker reads (§5 step 2a)."""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(RADARR, client=client, clock=clock)
        self._movies: tuple[float, list[RadarrMovie]] | None = None

    async def movies(self, connection: ArrConnection, refresh: bool = False) -> list[RadarrMovie]:
        """The whole library, cached for five minutes; `refresh` re-reads it now (§5 step 2a)."""
        now = self.clock()
        if not refresh and self._movies is not None and now - self._movies[0] < MOVIE_CACHE_TTL_S:
            return self._movies[1]
        body = await self._get(connection, "movie")
        movies = [_movie(item) for item in body] if isinstance(body, list) else []
        self._movies = (now, movies)
        return movies

    async def movie(self, connection: ArrConnection, movie_id: int) -> dict[str, Any]:
        body = await self._get(connection, f"movie/{movie_id}")
        return body if isinstance(body, dict) else {}


class SonarrClient(_ArrClient):
    """Sonarr, plus the series cache the TV wizard reads (§5 step 2b)."""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(SONARR, client=client, clock=clock)
        self._series: tuple[float, list[SonarrSeries]] | None = None

    async def series(self, connection: ArrConnection, refresh: bool = False) -> list[SonarrSeries]:
        """Every series Sonarr knows, cached for five minutes (§5 step 2b)."""
        now = self.clock()
        if not refresh and self._series is not None and now - self._series[0] < SERIES_CACHE_TTL_S:
            return self._series[1]
        body = await self._get(connection, "series")
        series = [_series(item) for item in body] if isinstance(body, list) else []
        self._series = (now, series)
        return series

    async def episodes(
        self, connection: ArrConnection, series_id: int, season: int | None = None
    ) -> list[SonarrEpisode]:
        """One season's episodes (or the whole series), small enough not to cache."""
        params = {"seriesId": str(series_id), "includeEpisodeFile": "true"}
        if season is not None:
            params["seasonNumber"] = str(season)
        body = await self._get(connection, "episode", params=params)
        return [_episode(item) for item in body] if isinstance(body, list) else []

    async def episode(self, connection: ArrConnection, episode_id: int) -> dict[str, Any]:
        body = await self._get(connection, f"episode/{episode_id}")
        return body if isinstance(body, dict) else {}


def _url(connection: ArrConnection, path: str) -> str:
    return f"{connection.url.rstrip('/')}/api/v3/{path}"


def _headers(connection: ArrConnection) -> dict[str, str]:
    return {"X-Api-Key": connection.api_key, "Accept": "application/json"}


def _movie(item: dict[str, Any]) -> RadarrMovie:
    return RadarrMovie(
        id=int(item.get("id", 0)),
        title=str(item.get("title") or ""),
        year=item.get("year") or None,
        monitored=bool(item.get("monitored")),
        has_file=bool(item.get("hasFile")),
        quality=_quality(item.get("movieFile")),
        poster=_poster(item),
    )


def _series(item: dict[str, Any]) -> SonarrSeries:
    seasons = tuple(_season(season) for season in item.get("seasons") or [] if season is not None)
    return SonarrSeries(
        id=int(item.get("id", 0)),
        title=str(item.get("title") or ""),
        # Anything Sonarr calls something else (anime) is numbered like a standard series.
        series_type="daily" if str(item.get("seriesType") or "") == "daily" else "standard",
        monitored=bool(item.get("monitored")),
        seasons=tuple(sorted(seasons, key=lambda season: season.number)),
        poster=_poster(item),
    )


def _season(season: dict[str, Any]) -> SonarrSeason:
    statistics = season.get("statistics") or {}
    return SonarrSeason(
        number=int(season.get("seasonNumber", 0)),
        episode_file_count=int(statistics.get("episodeFileCount") or 0),
        episode_count=int(statistics.get("episodeCount") or 0),
        total_episode_count=int(statistics.get("totalEpisodeCount") or 0),
    )


def _episode(item: dict[str, Any]) -> SonarrEpisode:
    return SonarrEpisode(
        id=int(item.get("id", 0)),
        season=int(item.get("seasonNumber", 0)),
        number=int(item.get("episodeNumber", 0)),
        title=str(item.get("title") or ""),
        air_date=_air_date(item.get("airDate")),
        has_file=bool(item.get("hasFile")),
        quality=_quality(item.get("episodeFile")),
    )


def _air_date(value: Any) -> date | None:
    """Sonarr's `airDate` is a plain `YYYY-MM-DD`, and null for an unscheduled episode."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _quality(file: Any) -> str | None:
    """`WEBDL-1080p` out of arr's nested quality block, for movies and episodes alike."""
    if not isinstance(file, dict):
        return None
    name = ((file.get("quality") or {}).get("quality") or {}).get("name")
    return str(name) if name else None


def _poster(item: dict[str, Any]) -> str | None:
    """The app's own poster. `remoteUrl` is absolute and public, so the browser can load it."""
    for image in item.get("images") or []:
        if (image or {}).get("coverType") != "poster":
            continue
        url = image.get("remoteUrl") or image.get("url")
        if url:
            return str(url)
    return None
