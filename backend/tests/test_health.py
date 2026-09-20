import httpx


async def test_healthz_returns_status_and_version_without_session(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "1.2.3"}
