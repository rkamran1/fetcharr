"""`GET /api/system/status` (requirements §11): the version plus the startup path self-test."""

import logging
from collections.abc import AsyncIterator
from datetime import date
from pathlib import Path

import httpx
import pytest
import respx
from fastapi import FastAPI

from app.config import Settings
from app.db.backup import PREFIX, nightly_backup
from app.main import create_app
from app.system.utils import COMPLETED_SUBFOLDERS
from tests.conftest import (
    RADARR_URL,
    SONARR_URL,
    configure_radarr,
    configure_sonarr,
    make_client,
    setup_account,
)
from tests.fake_ffmpeg import FakeFfmpeg


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


# ------------------------------- AC11: the /dev/dri + QSV/VAAPI check in the status


async def test_status_includes_the_transcode_report(signed_in: httpx.AsyncClient) -> None:
    """There is no iGPU here, so it says so plainly instead of pretending (§13.1)."""
    body = (await signed_in.get("/api/system/status")).json()

    transcode = body["transcode"]
    assert transcode["device"] is False
    assert transcode["ok"] is False
    # Startup only stats the device, so nothing has been encoded yet.
    assert transcode["tested"] is False
    assert transcode["profiles"] == []
    assert "/dev/dri" in transcode["message"]


async def test_transcode_test_reruns_the_check(
    app: FastAPI, signed_in: httpx.AsyncClient, tmp_path: Path, fake_ffmpeg: FakeFfmpeg
) -> None:
    """The Settings button: the full self-test, and the status then shows its result."""
    device = tmp_path / "renderD128"
    device.write_text("")
    app.state.hardware.device = device

    response = await signed_in.post("/api/system/transcode-test")

    assert response.status_code == 200
    report = response.json()
    assert report["tested"] is True
    assert report["ok"] is True
    assert [check["profile"] for check in report["profiles"]] == ["hevc-qsv", "hevc-vaapi"]
    # The report is remembered, so the status page shows it without re-running anything.
    assert (await signed_in.get("/api/system/status")).json()["transcode"] == report


async def test_transcode_test_reports_a_missing_device_without_running_ffmpeg(
    signed_in: httpx.AsyncClient, fake_ffmpeg: FakeFfmpeg
) -> None:
    response = await signed_in.post("/api/system/transcode-test")

    assert response.status_code == 200
    assert response.json()["device"] is False
    assert response.json()["tested"] is True
    assert fake_ffmpeg.calls == []


async def test_transcode_test_requires_a_session(app: FastAPI) -> None:
    async with make_client(app) as client:
        await setup_account(client)
        client.cookies.clear()

        assert (await client.post("/api/system/transcode-test")).status_code == 401
        assert (await client.get("/api/system/status")).status_code == 401


# --------------------------------------- AC4: the full report (tools, database, arr)


async def test_status_reports_every_field(
    app: FastAPI, signed_in: httpx.AsyncClient, settings: Settings
) -> None:
    body = (await signed_in.get("/api/system/status")).json()

    assert set(body) == {
        "version",
        "tools",
        "paths",
        "transcode",
        "database",
        "concurrency",
        "radarr",
        "sonarr",
    }
    assert set(body["tools"]) == {
        "ytdlp",
        "ffmpeg",
        "deno",
        "js_runtime",
        "aria2c",
        "update_on_start",
    }
    # The real ffmpeg is on PATH in CI and here, because the media fixtures need it.
    assert body["tools"]["ffmpeg"]
    assert body["tools"]["update_on_start"] is True
    assert body["tools"]["js_runtime"] == app.state.manager.js_runtime
    assert body["concurrency"] == {
        "downloads": settings.max_concurrent_downloads,
        "transcodes": settings.max_concurrent_transcodes,
    }
    assert body["database"]["path"].endswith(".db")
    assert body["database"]["size_bytes"] > 0
    assert body["database"]["last_backup"] is None
    assert body["radarr"] == {
        "configured": False,
        "ok": False,
        "version": None,
        "error": "Radarr is not configured in Settings",
    }


async def test_status_reports_the_newest_nightly_backup(
    app: FastAPI, signed_in: httpx.AsyncClient, tmp_path: Path
) -> None:
    backups = tmp_path / "backups"
    await nightly_backup(app.state.db, backups, date(2026, 5, 3))
    await nightly_backup(app.state.db, backups, date(2026, 5, 4))
    (backups / f"{PREFIX}20200101T000000000000Z.db").write_bytes(b"old")

    body = (await signed_in.get("/api/system/status")).json()

    assert body["database"]["last_backup"] == "fetcharr-2026-05-04.db"


async def test_status_reports_a_reachable_radarr(client: httpx.AsyncClient) -> None:
    await setup_account(client)
    await configure_radarr(client)

    async with respx.mock(base_url=RADARR_URL) as mock:
        mock.get("/api/v3/system/status").mock(
            return_value=httpx.Response(200, json={"version": "6.4.4"})
        )

        body = (await client.get("/api/system/status")).json()

    assert body["radarr"] == {
        "configured": True,
        "ok": True,
        "version": "6.4.4",
        "error": None,
    }


async def test_status_reports_an_unreachable_radarr(client: httpx.AsyncClient) -> None:
    """A down Radarr is one field of the report, not a failed report (AC4)."""
    await setup_account(client)
    await configure_radarr(client)
    await configure_sonarr(client)

    async with respx.mock(base_url=RADARR_URL) as radarr, respx.mock(base_url=SONARR_URL) as sonarr:
        radarr.get("/api/v3/system/status").mock(side_effect=httpx.ConnectError("refused"))
        sonarr.get("/api/v3/system/status").mock(
            return_value=httpx.Response(200, json={"version": "4.0.20"})
        )

        response = await client.get("/api/system/status")

    assert response.status_code == 200
    body = response.json()
    assert body["radarr"]["ok"] is False
    assert "unreachable" in body["radarr"]["error"]
    assert body["radarr"]["configured"] is True
    # The rest of the report is still there.
    assert body["sonarr"] == {"configured": True, "ok": True, "version": "4.0.20", "error": None}
    assert body["version"] == "1.2.3"


async def test_status_requires_a_session(app: FastAPI) -> None:
    async with make_client(app) as client:
        assert (await client.get("/api/system/status")).status_code == 401
