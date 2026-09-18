import asyncio
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

pytest_plugins = ["pytester", "tests.loop_guard"]

BACKEND_DIR = Path(__file__).resolve().parents[1]


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
