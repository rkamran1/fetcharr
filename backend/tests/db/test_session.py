import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import event, text

from app.db.session import Database


@pytest.fixture
async def db(tmp_path: Path) -> AsyncIterator[Database]:
    database = Database(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    try:
        yield database
    finally:
        await database.dispose()


async def _pragmas(session) -> dict[str, object]:
    names = ("journal_mode", "busy_timeout", "synchronous", "foreign_keys")
    return {name: (await session.execute(text(f"PRAGMA {name}"))).scalar() for name in names}


EXPECTED = {"journal_mode": "wal", "busy_timeout": 5000, "synchronous": 1, "foreign_keys": 1}


async def test_pragmas_on_every_connection(db: Database) -> None:
    # Two simultaneous read sessions force two distinct pooled connections.
    async with db.read_session() as first, db.read_session() as second:
        assert await _pragmas(first) == EXPECTED
        assert await _pragmas(second) == EXPECTED
        first_conn = await first.connection()
        second_conn = await second.connection()
        assert (await first_conn.get_raw_connection()) is not (
            await second_conn.get_raw_connection()
        )

    async with db.write_session() as session:
        assert await _pragmas(session) == EXPECTED


async def test_concurrent_writes_are_serialised(db: Database) -> None:
    async with db.write_session() as session:
        await session.execute(text("CREATE TABLE t (writer TEXT NOT NULL)"))

    events: list[str] = []

    async def write(name: str) -> None:
        async with db.write_session() as session:
            events.append(f"{name}:start")
            await session.execute(text("INSERT INTO t (writer) VALUES (:w)"), {"w": name})
            await asyncio.sleep(0.05)  # yield mid-transaction so the other writer tries to run
            events.append(f"{name}:end")

    await asyncio.gather(write("a"), write("b"))

    assert events in (
        ["a:start", "a:end", "b:start", "b:end"],
        ["b:start", "b:end", "a:start", "a:end"],
    )
    async with db.read_session() as session:
        rows = (await session.execute(text("SELECT writer FROM t ORDER BY writer"))).scalars()
        assert list(rows) == ["a", "b"]


async def test_write_transaction_begins_immediate(db: Database) -> None:
    writer_statements: list[str] = []
    reader_statements: list[str] = []

    def spy(target: list[str]):
        def _before(_conn, _cursor, statement, *_args) -> None:
            target.append(statement)

        return _before

    event.listen(db.writer.sync_engine, "before_cursor_execute", spy(writer_statements))
    event.listen(db.reader.sync_engine, "before_cursor_execute", spy(reader_statements))

    async with db.write_session() as session:
        await session.execute(text("SELECT 1"))
    async with db.read_session() as session:
        await session.execute(text("SELECT 1"))

    assert writer_statements[0] == "BEGIN IMMEDIATE"
    assert writer_statements[1] == "SELECT 1"
    assert reader_statements[0] == "BEGIN"
