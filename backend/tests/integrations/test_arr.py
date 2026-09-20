"""The arr clients: status codes become the error types the retry policy names (§7.5)."""

import json
from collections.abc import AsyncIterator
from datetime import date

import httpx
import pytest
import respx

from app.integrations.arr import (
    EPISODE_SCAN,
    MOVIE_SCAN,
    SERIES_CACHE_TTL_S,
    ArrAuthError,
    ArrClientError,
    ArrConnection,
    ArrServerError,
    RadarrClient,
    SonarrClient,
)
from tests.conftest import RADARR_API_KEY, RADARR_URL, SONARR_API_KEY, SONARR_URL

CONNECTION = ArrConnection(url=f"{RADARR_URL}/", api_key=RADARR_API_KEY)
SONARR_CONNECTION = ArrConnection(url=f"{SONARR_URL}/", api_key=SONARR_API_KEY)


@pytest.fixture
async def client() -> AsyncIterator[RadarrClient]:
    radarr = RadarrClient()
    try:
        yield radarr
    finally:
        await radarr.aclose()


@pytest.fixture
async def sonarr() -> AsyncIterator[SonarrClient]:
    client = SonarrClient()
    try:
        yield client
    finally:
        await client.aclose()


async def test_the_command_body_is_the_one_radarr_documents(client: RadarrClient) -> None:
    async with respx.mock(base_url=RADARR_URL) as mock:
        route = mock.post("/api/v3/command").mock(
            return_value=httpx.Response(201, json={"id": 42, "status": "queued"})
        )

        command_id = await client.send_command(
            CONNECTION, MOVIE_SCAN, "/web-downloads/completed/movies/X"
        )

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
            return_value=httpx.Response(
                200, json=[{"id": 1, "title": "Sintel", "year": 2010, "monitored": True}]
            )
        )

        first = await client.movies(CONNECTION)
        second = await client.movies(CONNECTION)

    assert route.call_count == 1
    assert first == second
    assert (
        first[0].id,
        first[0].title,
        first[0].monitored,
        first[0].has_file,
        first[0].quality,
        first[0].poster,
    ) == (1, "Sintel", True, False, None, None)


# ----------------------------------------------- M6 AC2/AC14: the Sonarr client


SERIES_BODY = [
    {
        "id": 3,
        "title": "Some Show",
        "seriesType": "standard",
        "monitored": True,
        "seasons": [
            {
                "seasonNumber": 1,
                "statistics": {
                    "episodeFileCount": 8,
                    "episodeCount": 8,
                    "totalEpisodeCount": 8,
                },
            },
            {"seasonNumber": 0, "statistics": {}},
        ],
        "images": [
            {"coverType": "poster", "url": "/MediaCover/3/poster.jpg"},
            {"coverType": "fanart", "remoteUrl": "https://artworks.thetvdb.com/fanart.jpg"},
        ],
    },
    # Sonarr calls anime something else; fetcharr numbers it like a standard series.
    {"id": 4, "title": "Some Anime", "seriesType": "anime", "seasons": []},
]


async def test_series_are_parsed_with_type_and_seasons(sonarr: SonarrClient) -> None:
    """AC2: id, title, series type and the seasons, in season order."""
    async with respx.mock(base_url=SONARR_URL) as mock:
        mock.get("/api/v3/series").mock(return_value=httpx.Response(200, json=SERIES_BODY))

        series = await sonarr.series(SONARR_CONNECTION)

    assert [(show.id, show.title, show.series_type) for show in series] == [
        (3, "Some Show", "standard"),
        (4, "Some Anime", "standard"),
    ]
    assert [(season.number, season.episode_file_count) for season in series[0].seasons] == [
        (0, 0),
        (1, 8),
    ]
    assert series[0].seasons[1].total_episode_count == 8


async def test_a_series_poster_is_the_absolute_remote_url(sonarr: SonarrClient) -> None:
    """AC14: `remoteUrl` wins, `url` is the fallback, and no poster means None."""
    body = [
        {"id": 1, "title": "Remote", "images": [{"coverType": "poster", "remoteUrl": "https://a"}]},
        {"id": 2, "title": "Local", "images": [{"coverType": "poster", "url": "/b.jpg"}]},
        {"id": 3, "title": "Banner only", "images": [{"coverType": "banner", "url": "/c.jpg"}]},
        {"id": 4, "title": "Nothing"},
    ]
    async with respx.mock(base_url=SONARR_URL) as mock:
        mock.get("/api/v3/series").mock(return_value=httpx.Response(200, json=body))

        series = await sonarr.series(SONARR_CONNECTION)

    assert [show.poster for show in series] == ["https://a", "/b.jpg", None, None]


async def test_the_series_list_is_cached_per_client(sonarr: SonarrClient) -> None:
    """AC2: one HTTP call inside the TTL, another once it has passed."""
    now = [0.0]
    sonarr.clock = lambda: now[0]

    async with respx.mock(base_url=SONARR_URL) as mock:
        route = mock.get("/api/v3/series").mock(return_value=httpx.Response(200, json=SERIES_BODY))

        await sonarr.series(SONARR_CONNECTION)
        now[0] += SERIES_CACHE_TTL_S - 1
        await sonarr.series(SONARR_CONNECTION)
        assert route.call_count == 1

        # `refresh` is the escape hatch, and the TTL is the other way past it.
        await sonarr.series(SONARR_CONNECTION, refresh=True)
        assert route.call_count == 2

        now[0] += SERIES_CACHE_TTL_S + 1
        await sonarr.series(SONARR_CONNECTION)

    assert route.call_count == 3


async def test_episodes_are_parsed_with_air_date_and_quality(sonarr: SonarrClient) -> None:
    """AC2: the fields the mapping table shows, with a real date and no file."""
    body = [
        {
            "id": 101,
            "seasonNumber": 1,
            "episodeNumber": 5,
            "title": "Fifth",
            "airDate": "2024-03-15",
            "hasFile": True,
            "episodeFile": {"quality": {"quality": {"name": "WEBDL-1080p"}}},
        },
        # An unaired episode has no date and no file.
        {"id": 102, "seasonNumber": 1, "episodeNumber": 6, "title": "Sixth", "airDate": None},
    ]
    async with respx.mock(base_url=SONARR_URL) as mock:
        route = mock.get("/api/v3/episode").mock(return_value=httpx.Response(200, json=body))

        episodes = await sonarr.episodes(SONARR_CONNECTION, 3, 1)

    assert [(e.id, e.season, e.number, e.title) for e in episodes] == [
        (101, 1, 5, "Fifth"),
        (102, 1, 6, "Sixth"),
    ]
    assert (episodes[0].air_date, episodes[0].has_file, episodes[0].quality) == (
        date(2024, 3, 15),
        True,
        "WEBDL-1080p",
    )
    assert (episodes[1].air_date, episodes[1].has_file, episodes[1].quality) == (None, False, None)
    assert dict(route.calls[0].request.url.params)["seasonNumber"] == "1"


async def test_the_episode_scan_command_carries_the_file_path(sonarr: SonarrClient) -> None:
    """AC8: the body §7.5 documents, with the episode file and `Move`."""
    path = "/web-downloads/completed/tv-shows/Some Show/Season 1/Some Show - S01E01 - Pilot.mkv"
    async with respx.mock(base_url=SONARR_URL) as mock:
        route = mock.post("/api/v3/command").mock(
            return_value=httpx.Response(201, json={"id": 42, "status": "queued"})
        )

        command_id = await sonarr.send_command(SONARR_CONNECTION, EPISODE_SCAN, path)

    assert command_id == "42"
    assert json.loads(route.calls[0].request.content) == {
        "name": "DownloadedEpisodesScan",
        "path": path,
        "importMode": "Move",
    }


async def test_sonarr_errors_carry_its_own_name(sonarr: SonarrClient) -> None:
    """The retry policy names types, but a person reads the message (§7.5)."""
    async with respx.mock(base_url=SONARR_URL) as mock:
        mock.get("/api/v3/series").mock(return_value=httpx.Response(401))

        with pytest.raises(ArrAuthError, match="Sonarr rejected the API key"):
            await sonarr.series(SONARR_CONNECTION)


async def test_a_season_carries_the_counts_that_say_what_is_missing(
    sonarr: SonarrClient,
) -> None:
    """AC15: missing is what Sonarr has no file for, whatever it is monitoring.

    Checked against Sonarr 4.0.20 during the M6 review: a series added unmonitored reports
    `episodeCount: 0` for every season, so counting that would hide the very series the
    owner came to fill (Breaking Bad, monitored false, 62 episodes, no files).
    """
    body = [
        {
            "id": 1,
            "title": "Airing",
            "monitored": True,
            "seasons": [
                # Ten episodes ordered, four aired, Sonarr holds one: three missing.
                {
                    "seasonNumber": 2,
                    "statistics": {
                        "episodeFileCount": 1,
                        "episodeCount": 4,
                        "totalEpisodeCount": 10,
                    },
                },
                # Complete.
                {
                    "seasonNumber": 1,
                    "statistics": {
                        "episodeFileCount": 8,
                        "episodeCount": 8,
                        "totalEpisodeCount": 8,
                    },
                },
            ],
        },
        # No statistics at all: nothing is known, so nothing is missing.
        {"id": 2, "title": "Bare", "seasons": [{"seasonNumber": 1}]},
    ]
    async with respx.mock(base_url=SONARR_URL) as mock:
        mock.get("/api/v3/series").mock(return_value=httpx.Response(200, json=body))

        series = await sonarr.series(SONARR_CONNECTION)

    airing, bare = series
    # Season 1 is complete; season 2 has ten episodes and one file.
    assert [(season.number, season.missing) for season in airing.seasons] == [(1, 0), (2, 9)]
    assert (airing.monitored, airing.missing) == (True, 9)
    # `episodeCount` still says how many have aired, which the card shows beside the gap.
    assert airing.seasons[1].episode_count == 4
    assert (bare.monitored, bare.missing) == (False, 0)


async def test_an_unmonitored_series_still_counts_as_missing(sonarr: SonarrClient) -> None:
    """The Breaking Bad case, verbatim from the dev Sonarr (M6 review).

    Added unmonitored: every season reports `episodeCount: 0`, because Sonarr only counts
    what it is hunting for. The episodes exist, and none of them is on disk.
    """
    body = [
        {
            "id": 1,
            "title": "Breaking Bad",
            "seriesType": "standard",
            "monitored": False,
            "seasons": [
                {
                    "seasonNumber": 1,
                    "monitored": False,
                    "statistics": {
                        "episodeFileCount": 0,
                        "episodeCount": 0,
                        "totalEpisodeCount": 7,
                    },
                },
                {
                    "seasonNumber": 2,
                    "monitored": False,
                    "statistics": {
                        "episodeFileCount": 0,
                        "episodeCount": 0,
                        "totalEpisodeCount": 13,
                    },
                },
            ],
        }
    ]
    async with respx.mock(base_url=SONARR_URL) as mock:
        mock.get("/api/v3/series").mock(return_value=httpx.Response(200, json=body))

        [show] = await sonarr.series(SONARR_CONNECTION)

    assert show.monitored is False
    assert [season.missing for season in show.seasons] == [7, 13]
    assert show.missing == 20
