"""The Radarr client: status codes become the error types the retry policy names (§7.5)."""

import json
from collections.abc import AsyncIterator

import httpx
import pytest
import respx

from app.integrations.arr import (
    ArrAuthError,
    ArrClientError,
    ArrConnection,
    ArrServerError,
    RadarrClient,
)
from tests.conftest import RADARR_API_KEY, RADARR_URL

CONNECTION = ArrConnection(url=f"{RADARR_URL}/", api_key=RADARR_API_KEY)


@pytest.fixture
async def client() -> AsyncIterator[RadarrClient]:
    radarr = RadarrClient()
    try:
        yield radarr
    finally:
        await radarr.aclose()


async def test_the_command_body_is_the_one_radarr_documents(client: RadarrClient) -> None:
    async with respx.mock(base_url=RADARR_URL) as mock:
        route = mock.post("/api/v3/command").mock(
            return_value=httpx.Response(201, json={"id": 42, "status": "queued"})
        )

        command_id = await client.send_command(CONNECTION, "/web-downloads/completed/movies/X")

    assert command_id == "42"
    assert json.loads(route.calls[0].request.content) == {
        "name": "DownloadedMoviesScan",
        "path": "/web-downloads/completed/movies/X",
        "importMode": "Move",
    }
    # A trailing slash on the configured URL must not double up in the path.
    assert str(route.calls[0].request.url) == f"{RADARR_URL}/api/v3/command"


async def test_command_status_is_read_back(client: RadarrClient) -> None:
    async with respx.mock(base_url=RADARR_URL) as mock:
        mock.get("/api/v3/command/42").mock(
            return_value=httpx.Response(200, json={"id": 42, "status": "completed"})
        )

        assert await client.command(CONNECTION, "42") == "completed"


@pytest.mark.parametrize(
    ("status", "error"),
    [(401, ArrAuthError), (403, ArrAuthError), (404, ArrClientError), (503, ArrServerError)],
)
async def test_status_codes_map_to_error_types(
    client: RadarrClient, status: int, error: type[Exception]
) -> None:
    async with respx.mock(base_url=RADARR_URL) as mock:
        mock.get("/api/v3/system/status").mock(return_value=httpx.Response(status))

        with pytest.raises(error):
            await client.system_status(CONNECTION)


async def test_rejections_are_collected_verbatim_in_both_shapes(client: RadarrClient) -> None:
    body = [
        {
            "rejections": [
                {"reason": "Not an upgrade for existing movie file(s)", "type": "permanent"}
            ]
        },
        {"rejections": ["Unknown movie"]},
        {"rejections": [{"reason": "Unknown movie"}]},
        {},
    ]
    async with respx.mock(base_url=RADARR_URL) as mock:
        route = mock.get("/api/v3/manualimport").mock(return_value=httpx.Response(200, json=body))

        reasons = await client.rejections(CONNECTION, "/web-downloads/completed/movies/X")

    assert reasons == ["Not an upgrade for existing movie file(s)", "Unknown movie"]
    assert route.calls[0].request.url.params["folder"] == "/web-downloads/completed/movies/X"


async def test_the_movie_list_is_cached_per_client(client: RadarrClient) -> None:
    now = [0.0]
    client.clock = lambda: now[0]
    async with respx.mock(base_url=RADARR_URL) as mock:
        route = mock.get("/api/v3/movie").mock(
            return_value=httpx.Response(200, json=[{"id": 1, "title": "Sintel", "year": 2010}])
        )

        first = await client.movies(CONNECTION)
        second = await client.movies(CONNECTION)

    assert route.call_count == 1
    assert first == second
    assert (first[0].id, first[0].title, first[0].has_file, first[0].quality) == (
        1,
        "Sintel",
        False,
        None,
    )
