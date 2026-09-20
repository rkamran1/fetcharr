"""The Radarr test button and the movie picker (§5 step 2a, §11; M5b AC2/AC3, M5c AC1-AC3)."""

from typing import Any

import httpx
import pytest
import respx
from fastapi import FastAPI

from app.integrations.arr import MOVIE_CACHE_TTL_S
from tests.conftest import RADARR_API_KEY, RADARR_URL, configure_radarr, setup_account

#: One movie of each shape "missing" has to tell apart (M5c AC1).
MOVIES: list[dict[str, Any]] = [
    # Monitored, and Radarr already has the file: wanted, but not missing.
    {
        "id": 7,
        "title": "Big Buck Bunny",
        "year": 2008,
        "monitored": True,
        "hasFile": True,
        "movieFile": {"quality": {"quality": {"name": "WEBDL-720p"}}},
        "images": [{"coverType": "poster", "remoteUrl": "https://image.tmdb.org/bbb.jpg"}],
    },
    # Monitored and fileless: missing.
    {
        "id": 9,
        "title": "Sintel",
        "year": 2010,
        "monitored": True,
        "hasFile": False,
        "images": [{"coverType": "poster", "remoteUrl": "https://image.tmdb.org/sintel.jpg"}],
    },
    # Fileless, but nobody asked Radarr for it, so not missing.
    {"id": 11, "title": "The Big Lebowski", "year": 1998, "monitored": False, "hasFile": False},
    # Missing, and its title also matches "big", so missing and q can be asked together.
    {"id": 13, "title": "Big Fish", "year": 2003, "monitored": True, "hasFile": False},
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
                "monitored": True,
                "has_file": True,
                "quality": "WEBDL-720p",
                "poster": "https://image.tmdb.org/bbb.jpg",
            },
            {
                "id": 11,
                "title": "The Big Lebowski",
                "year": 1998,
                "monitored": False,
                "has_file": False,
                "quality": None,
                "poster": None,
            },
            {
                "id": 13,
                "title": "Big Fish",
                "year": 2003,
                "monitored": True,
                "has_file": False,
                "quality": None,
                "poster": None,
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


# ------------------------------------------------- M5c AC1-AC3: the missing list


def _titles(response: httpx.Response) -> list[str]:
    return [movie["title"] for movie in response.json()["movies"]]


async def test_missing_returns_only_monitored_movies_without_a_file(
    signed_in: httpx.AsyncClient,
) -> None:
    async with respx.mock(base_url=RADARR_URL) as mock:
        mock.get("/api/v3/movie").mock(return_value=httpx.Response(200, json=MOVIES))

        missing = await signed_in.get("/api/arr/radarr/movies", params={"missing": "true"})
        everything = await signed_in.get("/api/arr/radarr/movies")

    # The one Radarr has a file for and the one it isn't monitoring are both left out.
    assert _titles(missing) == ["Sintel", "Big Fish"]
    # Without the flag the endpoint is exactly what M5b's picker asks for.
    assert _titles(everything) == ["Big Buck Bunny", "Sintel", "The Big Lebowski", "Big Fish"]


async def test_missing_narrows_by_query(signed_in: httpx.AsyncClient) -> None:
    async with respx.mock(base_url=RADARR_URL) as mock:
        mock.get("/api/v3/movie").mock(return_value=httpx.Response(200, json=MOVIES))

        response = await signed_in.get(
            "/api/arr/radarr/movies", params={"q": "big", "missing": "true"}
        )

    # "Big Buck Bunny" and "The Big Lebowski" match the query but aren't missing.
    assert _titles(response) == ["Big Fish"]


async def test_missing_is_served_from_the_same_cache(signed_in: httpx.AsyncClient) -> None:
    async with respx.mock(base_url=RADARR_URL) as mock:
        route = mock.get("/api/v3/movie").mock(return_value=httpx.Response(200, json=MOVIES))

        plain = await signed_in.get("/api/arr/radarr/movies", params={"q": "bunny"})
        missing = await signed_in.get("/api/arr/radarr/movies", params={"missing": "true"})

    assert _titles(plain) == ["Big Buck Bunny"]
    assert _titles(missing) == ["Sintel", "Big Fish"]
    # The filter runs over M5b's cached list, so opening the missing tab costs no call.
    assert route.call_count == 1


async def test_a_movie_without_monitored_is_not_missing(signed_in: httpx.AsyncClient) -> None:
    payload = [{"id": 21, "title": "Tears of Steel", "year": 2012, "hasFile": False}]
    async with respx.mock(base_url=RADARR_URL) as mock:
        mock.get("/api/v3/movie").mock(return_value=httpx.Response(200, json=payload))

        everything = await signed_in.get("/api/arr/radarr/movies")
        missing = await signed_in.get("/api/arr/radarr/movies", params={"missing": "true"})

    assert everything.json()["movies"][0]["monitored"] is False
    assert missing.json()["movies"] == []


async def test_refresh_re_reads_the_library(signed_in: httpx.AsyncClient) -> None:
    later = MOVIES + [
        {"id": 17, "title": "Tears of Steel", "year": 2012, "monitored": True, "hasFile": False}
    ]
    async with respx.mock(base_url=RADARR_URL) as mock:
        route = mock.get("/api/v3/movie").mock(
            side_effect=[httpx.Response(200, json=MOVIES), httpx.Response(200, json=later)]
        )

        first = await signed_in.get("/api/arr/radarr/movies", params={"missing": "true"})
        cached = await signed_in.get("/api/arr/radarr/movies", params={"missing": "true"})
        refreshed = await signed_in.get(
            "/api/arr/radarr/movies", params={"missing": "true", "refresh": "true"}
        )

    # The second call is the five-minute cache; only the third goes back to Radarr.
    assert route.call_count == 2
    assert _titles(first) == ["Sintel", "Big Fish"]
    assert _titles(cached) == ["Sintel", "Big Fish"]
    assert _titles(refreshed) == ["Sintel", "Big Fish", "Tears of Steel"]


async def test_movies_carry_the_poster_url(signed_in: httpx.AsyncClient) -> None:
    payload = [
        {
            "id": 1,
            "title": "Sintel",
            "year": 2010,
            "monitored": True,
            "hasFile": False,
            "images": [
                {"coverType": "fanart", "remoteUrl": "https://image.tmdb.org/fanart.jpg"},
                {
                    "coverType": "poster",
                    "url": "/MediaCover/1/poster.jpg",
                    "remoteUrl": "https://image.tmdb.org/poster.jpg",
                },
            ],
        },
        # Radarr sometimes has no artwork at all; the picker still has to render the row.
        {"id": 2, "title": "Home Video", "year": None, "monitored": True, "hasFile": False},
    ]
    async with respx.mock(base_url=RADARR_URL) as mock:
        mock.get("/api/v3/movie").mock(return_value=httpx.Response(200, json=payload))

        response = await signed_in.get("/api/arr/radarr/movies")

    posters = [movie["poster"] for movie in response.json()["movies"]]
    # The absolute remoteUrl wins: the browser can load it without Radarr's API key.
    assert posters == ["https://image.tmdb.org/poster.jpg", None]


# ------------------------------------------------------ the unhappy paths (M5b)


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
