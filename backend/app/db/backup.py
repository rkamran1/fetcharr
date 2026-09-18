"""Pre-migration SQLite backup (requirements §3.1 rule 7), run by the container entrypoint.

Usage: ``python -m app.db.backup`` — backs up the database named by ``DATABASE_URL`` into
``<db dir>/backups/`` if it exists, then keeps only the newest ``KEEP`` backups.
Runs before the app starts, outside any event loop, so plain sync I/O is fine here.
"""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.engine import make_url

from app.config import Settings

KEEP = 5
PREFIX = "fetcharr-premigrate-"


def backup_database(db_path: Path, backups_dir: Path, keep: int = KEEP) -> Path | None:
    if not db_path.is_file():
        return None
    backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    target = backups_dir / f"{PREFIX}{stamp}.db"
    with sqlite3.connect(db_path) as source, sqlite3.connect(target) as destination:
        source.backup(destination)
    source.close()
    destination.close()
    for old in sorted(backups_dir.glob(f"{PREFIX}*.db"))[:-keep]:
        old.unlink()
    return target


def main() -> None:
    database = make_url(Settings().database_url).database
    if not database:
        return
    db_path = Path(database)
    created = backup_database(db_path, db_path.parent / "backups")
    print(f"backup: {created}" if created else f"backup: no database at {db_path}, skipped")


if __name__ == "__main__":
    main()
