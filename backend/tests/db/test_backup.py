import sqlite3
from collections.abc import AsyncIterator
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy.engine import make_url

from app.db.backup import PREFIX, backup_database, backups_dir, nightly_backup
from app.db.base import utcnow
from app.db.session import Database
from app.requests.models import Request


def _make_db(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE t (x INTEGER)")
        conn.execute("INSERT INTO t VALUES (42)")
    conn.close()


def test_backup_created_and_pruned_to_five(tmp_path: Path) -> None:
    db_path = tmp_path / "fetcharr.db"
    _make_db(db_path)
    backups = tmp_path / "backups"
    backups.mkdir()
    old = [backups / f"{PREFIX}2020010{i}T000000000000Z.db" for i in range(1, 7)]
    for path in old:
        path.write_bytes(b"old")

    created = backup_database(db_path, backups)

    assert created is not None
    remaining = sorted(backups.glob(f"{PREFIX}*.db"))
    assert len(remaining) == 5
    assert remaining[-1] == created
    assert remaining[:4] == old[-4:]
    with sqlite3.connect(created) as conn:
        assert conn.execute("SELECT x FROM t").fetchall() == [(42,)]
    conn.close()


def test_no_backup_when_db_missing(tmp_path: Path) -> None:
    backups = tmp_path / "backups"

    assert backup_database(tmp_path / "missing.db", backups) is None
    assert not backups.exists()


@pytest.fixture
async def db(migrated_db_url: str) -> AsyncIterator[Database]:
    database = Database(migrated_db_url)
    try:
        yield database
    finally:
        await database.dispose()


async def _seed(db: Database, count: int) -> None:
    async with db.write_session() as session:
        for index in range(count):
            session.add(
                Request(
                    id=f"request-{index}",
                    media_type="other",
                    title=f"Video {index}",
                    options={},
                    created_at=utcnow(),
                )
            )


def _counts(path: Path) -> list[tuple[str, int]]:
    with sqlite3.connect(path) as conn:
        tables = [
            name
            for (name,) in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
            if not name.startswith("sqlite_")
        ]
        counts = [
            (name, conn.execute(f"SELECT count(*) FROM {name}").fetchone()[0]) for name in tables
        ]
    conn.close()
    return counts


async def test_nightly_backup_copies_every_row(db: Database, tmp_path: Path) -> None:
    await _seed(db, 3)
    backups = tmp_path / "backups"

    created = await nightly_backup(db, backups, date(2026, 5, 4))

    assert created == backups / "fetcharr-2026-05-04.db"
    source = Path(make_url(str(db.reader.url)).database or "")
    assert _counts(created) == _counts(source)
    assert dict(_counts(created))["requests"] == 3


async def test_nightly_backup_replaces_the_same_day(db: Database, tmp_path: Path) -> None:
    backups = tmp_path / "backups"
    await nightly_backup(db, backups, date(2026, 5, 4))
    await _seed(db, 2)

    created = await nightly_backup(db, backups, date(2026, 5, 4))

    assert sorted(path.name for path in backups.glob("fetcharr-*.db")) == ["fetcharr-2026-05-04.db"]
    assert dict(_counts(created))["requests"] == 2


async def test_nightly_backup_keeps_seven(db: Database, tmp_path: Path) -> None:
    backups = tmp_path / "backups"

    for day in range(1, 10):
        await nightly_backup(db, backups, date(2026, 5, day))

    assert sorted(path.name for path in backups.glob("fetcharr-*.db")) == [
        f"fetcharr-2026-05-0{day}.db" for day in range(3, 10)
    ]


async def test_nightly_backup_leaves_premigrate_backups(db: Database, tmp_path: Path) -> None:
    backups = tmp_path / "backups"
    backups.mkdir()
    premigrate = [backups / f"{PREFIX}2020010{i}T000000000000Z.db" for i in range(1, 6)]
    for path in premigrate:
        path.write_bytes(b"old")

    for day in range(1, 10):
        await nightly_backup(db, backups, date(2026, 5, day))

    assert sorted(backups.glob(f"{PREFIX}*.db")) == premigrate


def test_backups_dir_sits_next_to_the_database() -> None:
    assert backups_dir("sqlite+aiosqlite:////config/fetcharr.db") == Path("/config/backups")
    assert backups_dir("sqlite+aiosqlite://") is None
