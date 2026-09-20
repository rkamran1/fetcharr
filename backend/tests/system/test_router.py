"""`GET /api/system/status` (requirements §11): the version plus the startup path self-test."""

import logging
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from app.config import Settings
from app.main import create_app
from app.system.utils import COMPLETED_SUBFOLDERS
from tests.conftest import make_client, setup_account


@pytest.fixture
async def signed_in(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with make_client(app) as client:
        await setup_account(client)
        yield client


async def test_status_reports_the_path_self_test(
    signed_in: httpx.AsyncClient, settings: Settings
) -> None:
    response = await signed_in.get("/api/system/status")

    assert response.status_code == 200
    body = response.json()
    assert body["version"] == "1.2.3"
    assert body["paths"]["ok"] is True
    assert body["paths"]["same_filesystem"] is True
    assert {check["path"] for check in body["paths"]["checks"]} == {
        str(settings.incomplete_dir),
        *(str(settings.completed_dir / name) for name in COMPLETED_SUBFOLDERS),
    }


async def test_status_reports_a_read_only_folder(
    settings: Settings,
    static_dir: Path,
    downloads_dir: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    blocked = downloads_dir / "completed" / "other"
    blocked.mkdir(parents=True)
    blocked.chmod(0o500)
    try:
        application = create_app(settings, static_dir=static_dir)
        with caplog.at_level(logging.WARNING, logger="fetcharr"):
            async with application.router.lifespan_context(application):
                async with make_client(application) as client:
                    await setup_account(client)
                    body = (await client.get("/api/system/status")).json()
    finally:
        blocked.chmod(0o700)

    assert body["paths"]["ok"] is False
    failed = [check for check in body["paths"]["checks"] if not check["ok"]]
    assert [check["path"] for check in failed] == [str(blocked)]
    assert failed[0]["error"]
    # The log says what to do about it, instead of leaving a bare errno (AC16).
    warnings = [record.getMessage() for record in caplog.records]
    assert any(str(blocked) in message and "COMPLETED_DIR" in message for message in warnings)
