"""The arr test buttons and the pickers (§5 steps 2a/2b, §11; M5b, M5c and M6 AC1/AC2/AC14)."""

from typing import Any

import httpx
import pytest
import respx
from fastapi import FastAPI

from app.integrations.arr import MOVIE_CACHE_TTL_S, SERIES_CACHE_TTL_S
from tests.conftest import (
    RADARR_API_KEY,
    RADARR_URL,
    SONARR_API_KEY,
    SONARR_URL,
    configure_radarr,
    configure_sonarr,
    setup_account,
)

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


# ------------------------------------------------ M6 AC1/AC2/AC14: Sonarr


#: One standard series with two seasons, and one daily series (§5 step 2b).
SERIES: list[dict[str, Any]] = [
    {
        "id": 3,
        "title": "Some Show",
        "seriesType": "standard",
        "monitored": True,
        "seasons": [
            # Airing: four have aired, Sonarr holds one, so three are missing.
            {
                "seasonNumber": 2,
                "statistics": {
                    "episodeFileCount": 1,
                    "episodeCount": 4,
                    "totalEpisodeCount": 10,
                },
            },
            {
                "seasonNumber": 0,
                "statistics": {"episodeFileCount": 0, "episodeCount": 0, "totalEpisodeCount": 3},
            },
            {
                "seasonNumber": 1,
                "statistics": {"episodeFileCount": 8, "episodeCount": 8, "totalEpisodeCount": 8},
            },
        ],
        "images": [
            {"coverType": "banner", "remoteUrl": "https://artworks.thetvdb.com/banner.jpg"},
            {"coverType": "poster", "remoteUrl": "https://artworks.thetvdb.com/show.jpg"},
        ],
    },
    {
        "id": 5,
        "title": "Daily Show",
        "seriesType": "daily",
        # Complete: nothing missing, so the missing filter leaves it out.
        "monitored": True,
        "seasons": [
            {
                "seasonNumber": 2024,
                "statistics": {"episodeFileCount": 6, "episodeCount": 6, "totalEpisodeCount": 6},
            }
        ],
        "images": [{"coverType": "fanart", "url": "/MediaCover/5/fanart.jpg"}],
    },
]

EPISODES: list[dict[str, Any]] = [
    {
        "id": 101,
        "seriesId": 3,
        "seasonNumber": 1,
        "episodeNumber": 1,
        "title": "Pilot",
        "airDate": "2024-03-14",
        "hasFile": True,
        "episodeFile": {"quality": {"quality": {"name": "WEBDL-720p"}}},
    },
    {
        "id": 102,
        "seriesId": 3,
        "seasonNumber": 1,
        "episodeNumber": 2,
        "title": "Second",
        "airDate": "2024-03-15",
        "hasFile": False,
    },
]


@pytest.fixture
async def sonarr_signed_in(client: httpx.AsyncClient) -> httpx.AsyncClient:
    await setup_account(client)
    await configure_sonarr(client)
    return client


async def test_the_sonarr_test_reports_the_version(sonarr_signed_in: httpx.AsyncClient) -> None:
    """AC1: the Settings Test button, answering exactly as Radarr's does."""
    async with respx.mock(base_url=SONARR_URL) as mock:
        route = mock.get("/api/v3/system/status").mock(
            return_value=httpx.Response(200, json={"version": "4.0.20"})
        )

        response = await sonarr_signed_in.post("/api/arr/sonarr/test")

    assert response.status_code == 200
    assert response.json() == {"ok": True, "version": "4.0.20", "error": None}
    assert route.calls[0].request.headers["X-Api-Key"] == SONARR_API_KEY


async def test_the_sonarr_test_reports_a_bad_api_key(
    sonarr_signed_in: httpx.AsyncClient,
) -> None:
    """AC1: a 401 is a message to read, not an HTTP error to handle."""
    async with respx.mock(base_url=SONARR_URL) as mock:
        mock.get("/api/v3/system/status").mock(return_value=httpx.Response(401))

        response = await sonarr_signed_in.post("/api/arr/sonarr/test")

    body = response.json()
    assert body["ok"] is False
    assert "API key" in body["error"]
    assert "Sonarr" in body["error"]
    assert body["version"] is None


async def test_the_sonarr_test_reports_an_unreachable_sonarr(
    sonarr_signed_in: httpx.AsyncClient,
) -> None:
    async with respx.mock(base_url=SONARR_URL) as mock:
        mock.get("/api/v3/system/status").mock(side_effect=httpx.ConnectError("no route to host"))

        response = await sonarr_signed_in.post("/api/arr/sonarr/test")

    body = response.json()
    assert body["ok"] is False
    assert "unreachable" in body["error"]


async def test_the_sonarr_test_reports_that_sonarr_is_not_configured(
    client: httpx.AsyncClient,
) -> None:
    await setup_account(client)

    response = await client.post("/api/arr/sonarr/test")

    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert "not configured" in response.json()["error"]


async def test_series_are_returned_and_narrowed_by_the_query(
    sonarr_signed_in: httpx.AsyncClient,
) -> None:
    """AC2: id, title, series type and the seasons the wizard's dropdown lists."""
    async with respx.mock(base_url=SONARR_URL) as mock:
        route = mock.get("/api/v3/series").mock(return_value=httpx.Response(200, json=SERIES))

        everything = await sonarr_signed_in.get("/api/arr/sonarr/series")
        narrowed = await sonarr_signed_in.get("/api/arr/sonarr/series", params={"q": "daily show"})

    assert [show["title"] for show in everything.json()["series"]] == ["Some Show", "Daily Show"]
    show = everything.json()["series"][0]
    assert (show["id"], show["series_type"]) == (3, "standard")
    # Seasons come back in order, Specials first, with Sonarr's own counts.
    assert show["seasons"] == [
        {"number": 0, "episode_file_count": 0, "episode_count": 0, "total_episode_count": 3},
        {"number": 1, "episode_file_count": 8, "episode_count": 8, "total_episode_count": 8},
        {"number": 2, "episode_file_count": 1, "episode_count": 4, "total_episode_count": 10},
    ]
    assert everything.json()["series"][1]["series_type"] == "daily"
    assert [show["title"] for show in narrowed.json()["series"]] == ["Daily Show"]
    # The second lookup came out of the five-minute cache (AC2).
    assert route.call_count == 1


async def test_a_second_series_lookup_inside_five_minutes_hits_the_cache(
    app: FastAPI, sonarr_signed_in: httpx.AsyncClient
) -> None:
    """AC2: cached for five minutes, and re-read once that has passed."""
    now = [1000.0]
    app.state.sonarr.clock = lambda: now[0]

    async with respx.mock(base_url=SONARR_URL) as mock:
        route = mock.get("/api/v3/series").mock(return_value=httpx.Response(200, json=SERIES))

        await sonarr_signed_in.get("/api/arr/sonarr/series")
        now[0] += SERIES_CACHE_TTL_S - 1
        await sonarr_signed_in.get("/api/arr/sonarr/series")
        assert route.call_count == 1

        now[0] += 2
        await sonarr_signed_in.get("/api/arr/sonarr/series")

    assert route.call_count == 2


async def test_a_series_poster_reaches_the_picker(sonarr_signed_in: httpx.AsyncClient) -> None:
    """AC14: Sonarr's own poster, and None for a series that has none."""
    async with respx.mock(base_url=SONARR_URL) as mock:
        mock.get("/api/v3/series").mock(return_value=httpx.Response(200, json=SERIES))

        response = await sonarr_signed_in.get("/api/arr/sonarr/series")

    series = response.json()["series"]
    assert series[0]["poster"] == "https://artworks.thetvdb.com/show.jpg"
    # Fanart is not a poster, so the picker falls back to its placeholder.
    assert series[1]["poster"] is None


async def test_episodes_are_returned_for_one_season(
    sonarr_signed_in: httpx.AsyncClient,
) -> None:
    """AC2: number, title, air date, has-file and the quality Sonarr already holds."""
    async with respx.mock(base_url=SONARR_URL) as mock:
        route = mock.get("/api/v3/episode").mock(
            return_value=httpx.Response(200, json=list(reversed(EPISODES)))
        )

        response = await sonarr_signed_in.get(
            "/api/arr/sonarr/series/3/episodes", params={"season": 1}
        )

    assert response.status_code == 200
    # Ordered by episode number, however Sonarr returned them.
    assert response.json()["episodes"] == [
        {
            "id": 101,
            "season": 1,
            "number": 1,
            "title": "Pilot",
            "air_date": "2024-03-14",
            "has_file": True,
            "quality": "WEBDL-720p",
        },
        {
            "id": 102,
            "season": 1,
            "number": 2,
            "title": "Second",
            "air_date": "2024-03-15",
            "has_file": False,
            "quality": None,
        },
    ]
    query = dict(route.calls[0].request.url.params)
    assert query == {"seriesId": "3", "includeEpisodeFile": "true", "seasonNumber": "1"}


async def test_episodes_report_sonarr_unavailable(sonarr_signed_in: httpx.AsyncClient) -> None:
    async with respx.mock(base_url=SONARR_URL) as mock:
        mock.get("/api/v3/episode").mock(return_value=httpx.Response(503))

        response = await sonarr_signed_in.get("/api/arr/sonarr/series/3/episodes")

    assert response.status_code == 502
    assert "503" in response.json()["detail"]


async def test_series_report_an_unconfigured_sonarr(client: httpx.AsyncClient) -> None:
    await setup_account(client)

    response = await client.get("/api/arr/sonarr/series")

    assert response.status_code == 400
    assert "not configured" in response.json()["detail"]


# --------------------------------------------- M6 AC15: the missing series


#: Added unmonitored, so Sonarr reports nothing "wanted" — but the files aren't there.
#: This is the Breaking Bad shape the owner hit during the M6 review.
UNMONITORED = {
    "id": 9,
    "title": "Abandoned Show",
    "seriesType": "standard",
    "monitored": False,
    "seasons": [
        {
            "seasonNumber": 1,
            "statistics": {"episodeFileCount": 0, "episodeCount": 0, "totalEpisodeCount": 6},
        }
    ],
}

#: Complete: every episode Sonarr knows about is already on disk.
COMPLETE = {
    "id": 11,
    "title": "Finished Show",
    "seriesType": "standard",
    "monitored": True,
    "seasons": [
        {
            "seasonNumber": 1,
            "statistics": {"episodeFileCount": 6, "episodeCount": 6, "totalEpisodeCount": 6},
        }
    ],
}


async def test_series_can_be_narrowed_to_the_ones_missing_episodes(
    sonarr_signed_in: httpx.AsyncClient,
) -> None:
    """AC15: short of a file Sonarr knows it should have, whatever it is monitoring."""
    async with respx.mock(base_url=SONARR_URL) as mock:
        route = mock.get("/api/v3/series").mock(
            return_value=httpx.Response(200, json=[*SERIES, UNMONITORED, COMPLETE])
        )

        everything = await sonarr_signed_in.get("/api/arr/sonarr/series")
        missing = await sonarr_signed_in.get("/api/arr/sonarr/series", params={"missing": "true"})
        narrowed = await sonarr_signed_in.get(
            "/api/arr/sonarr/series", params={"missing": "true", "q": "abandoned"}
        )

    assert [show["title"] for show in everything.json()["series"]] == [
        "Some Show",
        "Daily Show",
        "Abandoned Show",
        "Finished Show",
    ]
    # "Daily Show" and "Finished Show" have every episode on disk. The unmonitored one is
    # listed, which is the whole point: Sonarr will never fill it on its own (M6 review).
    assert [show["title"] for show in missing.json()["series"]] == ["Some Show", "Abandoned Show"]
    assert [show["title"] for show in narrowed.json()["series"]] == ["Abandoned Show"]
    # The filter runs over the one cached list, so it costs Sonarr nothing (M5c).
    assert route.call_count == 1


async def test_refreshing_the_series_list_re_reads_sonarr(
    sonarr_signed_in: httpx.AsyncClient,
) -> None:
    """AC15: saving Sonarr settings doesn't clear the cache, so Refresh is the way past it."""
    later = [*SERIES, UNMONITORED | {"monitored": True, "title": "Newly Added"}]
    async with respx.mock(base_url=SONARR_URL) as mock:
        route = mock.get("/api/v3/series").mock(
            side_effect=[
                httpx.Response(200, json=SERIES),
                httpx.Response(200, json=later),
            ]
        )

        first = await sonarr_signed_in.get("/api/arr/sonarr/series", params={"missing": "true"})
        cached = await sonarr_signed_in.get("/api/arr/sonarr/series", params={"missing": "true"})
        refreshed = await sonarr_signed_in.get(
            "/api/arr/sonarr/series", params={"missing": "true", "refresh": "true"}
        )

    assert route.call_count == 2
    assert [show["title"] for show in first.json()["series"]] == ["Some Show"]
    assert [show["title"] for show in cached.json()["series"]] == ["Some Show"]
    assert [show["title"] for show in refreshed.json()["series"]] == ["Some Show", "Newly Added"]
