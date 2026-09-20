import httpx

from tests.conftest import create_api_key, setup_account

INDEX = "<!doctype html><title>fetcharr</title>"


async def test_root_serves_index(client: httpx.AsyncClient) -> None:
    response = await client.get("/")

    assert response.status_code == 200
    assert response.text == INDEX


async def test_unknown_client_route_falls_back_to_index(client: httpx.AsyncClient) -> None:
    response = await client.get("/queue")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.text == INDEX


async def test_static_asset_is_served(client: httpx.AsyncClient) -> None:
    response = await client.get("/assets/app.js")

    assert response.status_code == 200
    assert response.text == "console.log('fetcharr')"


async def test_unknown_api_path_returns_json_404(client: httpx.AsyncClient) -> None:
    await setup_account(client)
    api_key = await create_api_key(client)
    client.cookies.clear()

    for method in ("GET", "POST"):
        response = await client.request(
            method, "/api/does-not-exist", headers={"X-Api-Key": api_key}
        )

        assert response.status_code == 404
        assert response.headers["content-type"] == "application/json"
        assert response.json() == {"detail": "Not Found"}


async def test_path_escape_is_not_served(client: httpx.AsyncClient) -> None:
    for path in ("/..%2fsecret.txt", "/assets/..%2f..%2fsecret.txt", "/%2e%2e/secret.txt"):
        response = await client.get(path)

        assert "outside the static root" not in response.text
        assert response.text == INDEX
