import asyncio
import subprocess
import threading
from collections.abc import AsyncIterator, Callable, Iterator
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI

from app.config import Settings
from app.main import create_app

pytest_plugins = ["pytester", "tests.loop_guard", "tests.fake_ytdlp", "tests.fake_ffmpeg"]

BACKEND_DIR = Path(__file__).resolve().parents[1]
BASE_URL = "http://test"
USERNAME = "owner"
PASSWORD = "correct horse battery"
RADARR_URL = "http://radarr.test:7878"
RADARR_API_KEY = "0123456789abcdef0123456789abcdef"
SONARR_URL = "http://sonarr.test:8989"
SONARR_API_KEY = "fedcba9876543210fedcba9876543210"

SIZES = {
    "landscape": (1920, 1080),
    "vertical": (1080, 1920),
    "qhd": (2560, 1440),
    "uhd": (3840, 2160),
    "hd": (1280, 720),
    "small": (640, 360),
}


@pytest.fixture
async def migrated_db_url(tmp_path: Path) -> str:
    """A fresh SQLite database at the Alembic head."""
    url = f"sqlite+aiosqlite:///{tmp_path}/t.db"
    config = Config(BACKEND_DIR / "alembic.ini")
    config.attributes["database_url"] = url
    config.attributes["configure_logger"] = False
    # env.py calls asyncio.run(), which can't nest inside the test's event loop.
    await asyncio.to_thread(command.upgrade, config, "head")
    return url


@pytest.fixture
def static_dir(tmp_path: Path) -> Path:
    root = tmp_path / "static"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("<!doctype html><title>fetcharr</title>")
    (root / "assets" / "app.js").write_text("console.log('fetcharr')")
    (tmp_path / "secret.txt").write_text("outside the static root")
    return root


@pytest.fixture
def downloads_dir(tmp_path: Path) -> Path:
    """Stands in for the /web-downloads volume; tests never touch the real one."""
    root = tmp_path / "web-downloads"
    root.mkdir()
    return root


@pytest.fixture
def settings(migrated_db_url: str, downloads_dir: Path, tmp_path: Path) -> Settings:
    return Settings(
        app_version="1.2.3",
        database_url=migrated_db_url,
        completed_dir=downloads_dir / "completed",
        incomplete_dir=downloads_dir / "incomplete",
        # Never /config: the key is generated inside the test's own tmp_path (§8).
        secret_key_file=tmp_path / "secret.key",
    )


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


async def configure_radarr(
    client: httpx.AsyncClient, url: str = RADARR_URL, api_key: str = RADARR_API_KEY
) -> None:
    response = await client.patch(
        "/api/settings", json={"radarr_url": url, "radarr_api_key": api_key}
    )
    assert response.status_code == 200, response.text


async def configure_sonarr(
    client: httpx.AsyncClient, url: str = SONARR_URL, api_key: str = SONARR_API_KEY
) -> None:
    response = await client.patch(
        "/api/settings", json={"sonarr_url": url, "sonarr_api_key": api_key}
    )
    assert response.status_code == 200, response.text


async def create_api_key(client: httpx.AsyncClient) -> str:
    response = await client.post("/api/auth/api-key")
    assert response.status_code == 200
    return response.json()["api_key"]


# Sync on purpose: ruff's ASYNC240 forbids pathlib I/O inside an async test body.
def exists(path: Path) -> bool:
    return path.exists()


def is_file(path: Path) -> bool:
    return path.is_file()


def names(directory: Path) -> list[str]:
    return sorted(entry.name for entry in directory.iterdir()) if directory.is_dir() else []


async def wait_until(
    condition: Callable[[], bool], *, seconds: float = 10.0, interval: float = 0.02
) -> None:
    """Poll for a side effect a subprocess produces, where there is no event to await."""
    async with asyncio.timeout(seconds):
        while True:
            if condition():
                return
            await asyncio.sleep(interval)


def _ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


@pytest.fixture(scope="session")
def media(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """Tiny real media files generated with ffmpeg lavfi (one per resolution + audio only)."""
    root = tmp_path_factory.mktemp("media")
    files: dict[str, Path] = {}
    for name, (width, height) in SIZES.items():
        files[name] = root / f"{name}.mkv"
        _ffmpeg(
            "-f",
            "lavfi",
            "-i",
            f"testsrc=size={width}x{height}:rate=1:duration=1",
            "-f",
            "lavfi",
            "-i",
            "sine=duration=1",
            "-c:v",
            "mpeg4",
            "-c:a",
            "aac",
            "-shortest",
            str(files[name]),
        )
    files["audio"] = root / "audio.mka"
    _ffmpeg("-f", "lavfi", "-i", "sine=duration=1", "-c:a", "aac", str(files["audio"]))
    files["garbage"] = root / "garbage.mkv"
    files["garbage"].write_bytes(b"not a video" * 100)
    # A plain MP4 the real yt-dlp can fetch from the local server (no internet, §16).
    files["served"] = root / "served.mp4"
    _ffmpeg(
        "-f",
        "lavfi",
        "-i",
        "testsrc=size=640x360:rate=10:duration=2",
        "-f",
        "lavfi",
        "-i",
        "sine=duration=2",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        str(files["served"]),
    )
    return files


@pytest.fixture
def media_server(media: dict[str, Path], tmp_path: Path) -> Iterator[str]:
    """Serve one MP4 over 127.0.0.1 so yt-dlp's generic extractor has something real."""
    root = tmp_path / "served"
    root.mkdir()
    (root / "video.mp4").write_bytes(media["served"].read_bytes())
    handler = partial(_QuietHandler, directory=str(root))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/video.mp4"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - stdlib signature
        pass
