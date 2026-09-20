"""Radarr's v3 API: one shared client, the cached movie list and the import command (§7.5).

A library module: no FastAPI, no database, no domain imports. Everything that decides what
to do with an answer (retry, checkpoint, verify) lives in the jobs pipeline; this module
only speaks HTTP and maps status codes onto the error types the retry policy names.
"""

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx
from tenacity import wait_chain, wait_fixed

#: The movie list is big and changes rarely; the picker re-reads it at most this often.
MOVIE_CACHE_TTL_S = 300.0
CONNECT_TIMEOUT_S = 5.0
READ_TIMEOUT_S = 30.0

#: The import retry schedule from requirements §6.1: 10 s, 60 s, 300 s over four attempts.
IMPORT_WAIT = wait_chain(wait_fixed(10), wait_fixed(60), wait_fixed(300))
IMPORT_ATTEMPTS = 4
POLL_INTERVAL_S = 2.0
COMMAND_TIMEOUT_S = 600.0

MOVIE_SCAN = "DownloadedMoviesScan"
IMPORT_MODE = "Move"
#: Radarr reports these when a command is done; anything else means keep polling.
FINISHED = ("completed", "failed", "aborted")


class ArrError(Exception):
    """Radarr could not be asked, or answered with an error."""


class ArrAuthError(ArrError):
    """401/403: the API key is wrong. Never retried (requirements §6.1)."""


class ArrClientError(ArrError):
    """Another 4xx: the request itself is wrong, so retrying changes nothing."""


class ArrServerError(ArrError):
    """5xx: Radarr is unwell right now, so this one is retried."""


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


class RadarrClient:
    """Long-lived: one connection pool, one movie cache and one import lock per process."""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(READ_TIMEOUT_S, connect=CONNECT_TIMEOUT_S)
        )
        self.clock = clock
        self._movies: tuple[float, list[RadarrMovie]] | None = None
        #: Import commands to one arr app run one at a time (requirements §6.1).
        self.import_lock = asyncio.Lock()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def system_status(self, connection: ArrConnection) -> str:
        """The Radarr version, which doubles as the connection test (§7.5)."""
        body = await self._get(connection, "system/status")
        return str(body.get("version") or "unknown")

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

    async def send_command(self, connection: ArrConnection, folder: str) -> str:
        """`DownloadedMoviesScan` with `importMode: Move`, and the command id back (§7.5)."""
        body = await self._post(
            connection,
            "command",
            {"name": MOVIE_SCAN, "path": folder, "importMode": IMPORT_MODE},
        )
        return str(body.get("id", "")) if isinstance(body, dict) else ""

    async def command(self, connection: ArrConnection, command_id: str) -> str:
        """The command's status: `queued`, `started`, `completed`, `failed` or `aborted`."""
        body = await self._get(connection, f"command/{command_id}")
        return str(body.get("status", "")) if isinstance(body, dict) else ""

    async def rejections(self, connection: ArrConnection, folder: str) -> list[str]:
        """Why Radarr left the files where they are, verbatim and de-duplicated (§7.5)."""
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
        return _body(response)

    async def _post(self, connection: ArrConnection, path: str, json: dict[str, Any]) -> Any:
        response = await self._client.post(
            _url(connection, path), headers=_headers(connection), json=json
        )
        return _body(response)


def _url(connection: ArrConnection, path: str) -> str:
    return f"{connection.url.rstrip('/')}/api/v3/{path}"


def _headers(connection: ArrConnection) -> dict[str, str]:
    return {"X-Api-Key": connection.api_key, "Accept": "application/json"}


def _body(response: httpx.Response) -> Any:
    """One place where a status code becomes the exception type the retry policy names."""
    status = response.status_code
    if status in (401, 403):
        raise ArrAuthError("Radarr rejected the API key; check it in Settings")
    if status >= 500:
        raise ArrServerError(f"Radarr answered {status}")
    if status >= 400:
        raise ArrClientError(f"Radarr answered {status}: {response.text[:200]}")
    if not response.content:
        return {}
    try:
        return response.json()
    except ValueError as error:
        raise ArrClientError(f"Radarr sent a body that isn't JSON: {error}") from error


def _movie(item: dict[str, Any]) -> RadarrMovie:
    quality = (((item.get("movieFile") or {}).get("quality") or {}).get("quality") or {}).get(
        "name"
    )
    return RadarrMovie(
        id=int(item.get("id", 0)),
        title=str(item.get("title") or ""),
        year=item.get("year") or None,
        monitored=bool(item.get("monitored")),
        has_file=bool(item.get("hasFile")),
        quality=str(quality) if quality else None,
        poster=_poster(item),
    )


def _poster(item: dict[str, Any]) -> str | None:
    """Radarr's own poster. `remoteUrl` is absolute and public, so the browser can load it."""
    for image in item.get("images") or []:
        if (image or {}).get("coverType") != "poster":
            continue
        url = image.get("remoteUrl") or image.get("url")
        if url:
            return str(url)
    return None
