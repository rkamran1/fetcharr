from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from app.config import Settings
from app.main import create_app

BASE_URL = "http://test"
USERNAME = "owner"
PASSWORD = "correct horse battery"


@pytest.fixture
def static_dir(tmp_path: Path) -> Path:
    root = tmp_path / "static"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("<!doctype html><title>fetcharr</title>")
    (root / "assets" / "app.js").write_text("console.log('fetcharr')")
    (tmp_path / "secret.txt").write_text("outside the static root")
    return root


@pytest.fixture
def settings(migrated_db_url: str) -> Settings:
    return Settings(app_version="1.2.3", database_url=migrated_db_url)


@pytest.fixture
async def app(settings: Settings, static_dir: Path) -> AsyncIterator[FastAPI]:
    application = create_app(settings, static_dir=static_dir)
    async with application.router.lifespan_context(application):
        yield application


def make_client(app: FastAPI, ip: str = "127.0.0.1") -> httpx.AsyncClient:
    """A client that behaves like a same-origin browser: it keeps cookies and sends Origin."""
    transport = httpx.ASGITransport(app=app, client=(ip, 50000))
    return httpx.AsyncClient(transport=transport, base_url=BASE_URL, headers={"Origin": BASE_URL})


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with make_client(app) as c:
        yield c


async def setup_account(client: httpx.AsyncClient) -> httpx.Response:
    response = await client.post(
        "/api/auth/setup", json={"username": USERNAME, "password": PASSWORD}
    )
    assert response.status_code == 201
    return response


async def login(client: httpx.AsyncClient, password: str = PASSWORD) -> httpx.Response:
    return await client.post("/api/auth/login", json={"username": USERNAME, "password": password})


async def create_api_key(client: httpx.AsyncClient) -> str:
    response = await client.post("/api/auth/api-key")
    assert response.status_code == 200
    return response.json()["api_key"]
