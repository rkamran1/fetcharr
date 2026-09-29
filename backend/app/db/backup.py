"""SQLite backups (requirements §3.1 rule 7): before each migration, and nightly.

The pre-migration half runs as ``python -m app.db.backup`` from the container entrypoint,
before the app starts, so plain sync I/O is fine there. The nightly half runs inside the
app, through the single writer path, and keeps its own count of its own files.
"""

import asyncio
import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy.engine import make_url

from app.config import Settings
from app.db.session import Database

KEEP = 5
PREFIX = "fetcharr-premigrate-"
#: The nightly copies: `fetcharr-<date>.db`, kept apart from the pre-migration ones above.
NIGHTLY_PREFIX = "fetcharr-"
NIGHTLY_GLOB = f"{NIGHTLY_PREFIX}[0-9]*.db"
KEEP_NIGHTLY = 7


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


def nightly_name(day: date) -> str:
    return f"{NIGHTLY_PREFIX}{day.isoformat()}.db"


async def nightly_backup(
    db: Database, backups_dir: Path, day: date, keep: int = KEEP_NIGHTLY
) -> Path:
    """`VACUUM INTO` a dated copy, then keep only the newest `keep` of them (§3.1 rule 7)."""
    await asyncio.to_thread(backups_dir.mkdir, parents=True, exist_ok=True)
    target = backups_dir / nightly_name(day)
    # VACUUM INTO refuses an existing file, so a second run on one day replaces the first.
    await asyncio.to_thread(target.unlink, True)
    source = make_url(str(db.writer.url)).database
    if not source:
        raise ValueError("the database has no file to back up")
    # VACUUM refuses to run inside a transaction, so it goes through its own connection,
    # under the write lock, off the event loop.
    async with db.writer_lock():
        await asyncio.to_thread(_vacuum_into, Path(source), target)
    await asyncio.to_thread(_prune_nightly, backups_dir, keep)
    return target


def _vacuum_into(db_path: Path, target: Path) -> None:
    connection = sqlite3.connect(db_path, isolation_level=None)
    try:
        connection.execute("VACUUM INTO ?", (str(target),))
    finally:
        connection.close()


def _prune_nightly(backups_dir: Path, keep: int) -> None:
    """Only the dated copies are counted; the pre-migration backups keep their own count."""
    dated = sorted(
        path for path in backups_dir.glob(NIGHTLY_GLOB) if not path.name.startswith(PREFIX)
    )
    for old in dated[:-keep] if keep else dated:
        old.unlink(missing_ok=True)


def backups_dir(database_url: str) -> Path | None:
    """Where both kinds of backup live: next to the database file itself."""
    database = make_url(database_url).database
    return Path(database).parent / "backups" if database else None


def main() -> None:
    database = make_url(Settings().database_url).database
    if not database:
        return
    db_path = Path(database)
    created = backup_database(db_path, db_path.parent / "backups")
    print(f"backup: {created}" if created else f"backup: no database at {db_path}, skipped")


if __name__ == "__main__":
    main()
