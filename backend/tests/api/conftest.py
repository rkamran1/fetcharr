from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from app.config import Settings
from app.main import create_app


@pytest.fixture
def static_dir(tmp_path: Path) -> Path:
    root = tmp_path / "static"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("<!doctype html><title>fetcharr</title>")
    (root / "assets" / "app.js").write_text("console.log('fetcharr')")
    (tmp_path / "secret.txt").write_text("outside the static root")
    return root


@pytest.fixture
async def app(tmp_path: Path, static_dir: Path) -> AsyncIterator[FastAPI]:
    settings = Settings(app_version="1.2.3", database_url=f"sqlite+aiosqlite:///{tmp_path}/t.db")
    application = create_app(settings, static_dir=static_dir)
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
