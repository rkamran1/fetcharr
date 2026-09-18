import sqlite3
from pathlib import Path

from app.db.backup import PREFIX, backup_database


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
