"""AC7: the presets endpoints (requirements §11)."""

import httpx
import pytest

from tests.conftest import setup_account

OPTIONS = {"quality": "1080p", "container": "mkv"}
ENDPOINTS = [
    ("GET", "/api/presets", None),
    ("POST", "/api/presets", {"name": "p", "media_type": "any", "options": OPTIONS}),
    ("PATCH", "/api/presets/1", {"name": "p"}),
    ("DELETE", "/api/presets/1", None),
]


@pytest.mark.parametrize(("method", "path", "body"), ENDPOINTS)
async def test_presets_endpoints_require_session(
    client: httpx.AsyncClient, method: str, path: str, body: dict | None
) -> None:
    response = await client.request(method, path, json=body)

    assert response.status_code == 401


async def test_crud_round_trip(client: httpx.AsyncClient) -> None:
    await setup_account(client)

    assert (await client.get("/api/presets")).json() == []

    created = await client.post(
        "/api/presets",
        json={"name": "1080p mkv remux", "media_type": "movie", "options": OPTIONS},
    )
    assert created.status_code == 201, created.text
    preset = created.json()
    assert preset["name"] == "1080p mkv remux"
    assert preset["media_type"] == "movie"
    assert preset["is_default"] is False
    # Stored as full options, so a preset always carries every field the builder reads.
    assert preset["options"]["quality"] == "1080p"
    assert preset["options"]["subtitles"] == {
        "mode": "off",
        "languages": [],
        "include_auto_captions": False,
    }

    listed = await client.get("/api/presets")
    assert [p["id"] for p in listed.json()] == [preset["id"]]

    patched = await client.patch(
        f"/api/presets/{preset['id']}",
        json={"name": "Phone-friendly mp4 x265", "options": {**OPTIONS, "container": "mp4"}},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["name"] == "Phone-friendly mp4 x265"
    assert patched.json()["options"]["container"] == "mp4"
    assert patched.json()["media_type"] == "movie"

    deleted = await client.delete(f"/api/presets/{preset['id']}")
    assert deleted.status_code == 204
    assert (await client.get("/api/presets")).json() == []


@pytest.mark.parametrize(
    ("method", "path"), [("PATCH", "/api/presets/99"), ("DELETE", "/api/presets/99")]
)
async def test_unknown_preset_is_404(client: httpx.AsyncClient, method: str, path: str) -> None:
    await setup_account(client)

    response = await client.request(method, path, json={"name": "x"})

    assert response.status_code == 404


@pytest.mark.parametrize(
    "options",
    [
        {**OPTIONS, "exec": "rm -rf /"},
        {**OPTIONS, "rate_limit": "5G/s"},
        {**OPTIONS, "sponsorblock": {"mode": "remove", "categories": ["poi_highlight"]}},
        {**OPTIONS, "subtitles": {"mode": "sidecar", "languages": ["en_US"]}},
    ],
    ids=["unknown-field", "bad-rate", "bad-category", "bad-language"],
)
async def test_rejects_options_the_allow_list_forbids(
    client: httpx.AsyncClient, options: dict
) -> None:
    await setup_account(client)

    response = await client.post(
        "/api/presets", json={"name": "bad", "media_type": "any", "options": options}
    )

    assert response.status_code == 422


async def test_an_any_preset_is_offered_to_every_wizard(client: httpx.AsyncClient) -> None:
    """`any` is one media type among four: the wizards filter on it, the API just stores it."""
    await setup_account(client)

    for media_type in ("movie", "tv", "other", "any"):
        created = await client.post(
            "/api/presets",
            json={"name": media_type, "media_type": media_type, "options": OPTIONS},
        )
        assert created.status_code == 201, created.text

    listed = (await client.get("/api/presets")).json()

    assert sorted(p["media_type"] for p in listed) == ["any", "movie", "other", "tv"]
