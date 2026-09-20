"""The Radarr test button and the movie picker (requirements §5 step 2a, §11, AC2, AC3)."""

from typing import Any

import httpx
import pytest
import respx
from fastapi import FastAPI

from app.integrations.arr import MOVIE_CACHE_TTL_S
from tests.conftest import RADARR_API_KEY, RADARR_URL, configure_radarr, setup_account

MOVIES: list[dict[str, Any]] = [
    {
        "id": 7,
        "title": "Big Buck Bunny",
        "year": 2008,
        "hasFile": True,
        "movieFile": {"quality": {"quality": {"name": "WEBDL-720p"}}},
    },
    {"id": 9, "title": "Sintel", "year": 2010, "hasFile": False},
    {"id": 11, "title": "The Big Lebowski", "year": 1998, "hasFile": False},
]


@pytest.fixture
async def signed_in(client: httpx.AsyncClient) -> httpx.AsyncClient:
    await setup_account(client)
    await configure_radarr(client)
    return client


# ------------------------------------------------------------------- AC2: test


async def test_test_returns_the_radarr_version(signed_in: httpx.AsyncClient) -> None:
    async with respx.mock(base_url=RADARR_URL) as mock:
        route = mock.get("/api/v3/system/status").mock(
            return_value=httpx.Response(200, json={"version": "6.4.4"})
        )

        response = await signed_in.post("/api/arr/radarr/test")

    assert response.status_code == 200
    assert response.json() == {"ok": True, "version": "6.4.4", "error": None}
    assert route.calls[0].request.headers["X-Api-Key"] == RADARR_API_KEY


async def test_test_reports_a_bad_api_key(signed_in: httpx.AsyncClient) -> None:
    async with respx.mock(base_url=RADARR_URL) as mock:
        mock.get("/api/v3/system/status").mock(return_value=httpx.Response(401))

        response = await signed_in.post("/api/arr/radarr/test")

    body = response.json()
    assert body["ok"] is False
    assert "API key" in body["error"]
    assert body["version"] is None


async def test_test_reports_an_unreachable_host(signed_in: httpx.AsyncClient) -> None:
    async with respx.mock(base_url=RADARR_URL) as mock:
        mock.get("/api/v3/system/status").mock(side_effect=httpx.ConnectError("no route to host"))

        response = await signed_in.post("/api/arr/radarr/test")

    body = response.json()
    assert body["ok"] is False
    assert RADARR_URL in body["error"]
    assert "unreachable" in body["error"]


async def test_test_reports_radarr_not_configured(client: httpx.AsyncClient) -> None:
    await setup_account(client)

    response = await client.post("/api/arr/radarr/test")

    assert response.json() == {
        "ok": False,
        "version": None,
        "error": "Radarr is not configured in Settings",
    }


async def test_test_requires_a_session(client: httpx.AsyncClient) -> None:
    await setup_account(client)
    client.cookies.clear()

    assert (await client.post("/api/arr/radarr/test")).status_code == 401


# ----------------------------------------------------------------- AC3: movies


async def test_movies_filters_by_query(signed_in: httpx.AsyncClient) -> None:
    async with respx.mock(base_url=RADARR_URL) as mock:
        mock.get("/api/v3/movie").mock(return_value=httpx.Response(200, json=MOVIES))

        response = await signed_in.get("/api/arr/radarr/movies", params={"q": "big"})

    assert response.status_code == 200
    assert response.json() == {
        "movies": [
            {
                "id": 7,
                "title": "Big Buck Bunny",
                "year": 2008,
                "has_file": True,
                "quality": "WEBDL-720p",
            },
            {
                "id": 11,
                "title": "The Big Lebowski",
                "year": 1998,
                "has_file": False,
                "quality": None,
            },
        ]
    }


async def test_movies_are_served_from_the_cache(signed_in: httpx.AsyncClient) -> None:
    async with respx.mock(base_url=RADARR_URL) as mock:
        route = mock.get("/api/v3/movie").mock(return_value=httpx.Response(200, json=MOVIES))

        first = await signed_in.get("/api/arr/radarr/movies", params={"q": "sintel"})
        second = await signed_in.get("/api/arr/radarr/movies", params={"q": "bunny"})

    assert first.json()["movies"][0]["title"] == "Sintel"
    assert second.json()["movies"][0]["title"] == "Big Buck Bunny"
    assert route.call_count == 1


async def test_movies_refresh_after_the_cache_expires(
    app: FastAPI, signed_in: httpx.AsyncClient
) -> None:
    now = [1000.0]
    app.state.radarr.clock = lambda: now[0]

    async with respx.mock(base_url=RADARR_URL) as mock:
        route = mock.get("/api/v3/movie").mock(return_value=httpx.Response(200, json=MOVIES))

        await signed_in.get("/api/arr/radarr/movies")
        now[0] += MOVIE_CACHE_TTL_S + 1
        await signed_in.get("/api/arr/radarr/movies")

    assert route.call_count == 2


async def test_movies_report_an_unconfigured_radarr(client: httpx.AsyncClient) -> None:
    await setup_account(client)

    response = await client.get("/api/arr/radarr/movies")

    assert response.status_code == 400
    assert response.json()["detail"] == "Radarr is not configured in Settings"


async def test_movies_report_a_radarr_that_answers_badly(signed_in: httpx.AsyncClient) -> None:
    async with respx.mock(base_url=RADARR_URL) as mock:
        mock.get("/api/v3/movie").mock(return_value=httpx.Response(503))

        response = await signed_in.get("/api/arr/radarr/movies")

    assert response.status_code == 502
    assert "503" in response.json()["detail"]


async def test_movies_require_a_session(client: httpx.AsyncClient) -> None:
    await setup_account(client)
    client.cookies.clear()

    assert (await client.get("/api/arr/radarr/movies")).status_code == 401
