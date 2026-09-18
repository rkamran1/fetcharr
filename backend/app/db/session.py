"""Database access following the SQLite rules in requirements §3.1.

- Every connection gets the WAL/busy_timeout/synchronous/foreign_keys PRAGMAs.
- Reads use their own engine (connection pool); readers never block the writer.
- All writes go through ``Database.write_session()``: one asyncio lock, one dedicated
  writer connection, and ``BEGIN IMMEDIATE``. Keep write transactions short and never
  await a subprocess or network call while one is open.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import Connection, event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import AsyncAdaptedQueuePool

PRAGMAS = (
    "PRAGMA journal_mode=WAL",
    "PRAGMA busy_timeout=5000",
    "PRAGMA synchronous=NORMAL",
    "PRAGMA foreign_keys=ON",
)


def _install_listeners(engine: AsyncEngine, begin_statement: str) -> None:
    @event.listens_for(engine.sync_engine, "connect")
    def _on_connect(dbapi_connection, _connection_record) -> None:
        # Hand transaction control to SQLAlchemy's "begin" event instead of the
        # sqlite3 driver's implicit deferred BEGIN.
        dbapi_connection.isolation_level = None
        cursor = dbapi_connection.cursor()
        for pragma in PRAGMAS:
            cursor.execute(pragma)
        cursor.close()

    @event.listens_for(engine.sync_engine, "begin")
    def _on_begin(connection: Connection) -> None:
        connection.exec_driver_sql(begin_statement)


class Database:
    def __init__(self, url: str) -> None:
        self.reader = create_async_engine(url)
        self.writer = create_async_engine(
            url, poolclass=AsyncAdaptedQueuePool, pool_size=1, max_overflow=0
        )
        _install_listeners(self.reader, "BEGIN")
        _install_listeners(self.writer, "BEGIN IMMEDIATE")
        self._read_sessions = async_sessionmaker(self.reader, expire_on_commit=False)
        self._write_sessions = async_sessionmaker(self.writer, expire_on_commit=False)
        self._write_lock = asyncio.Lock()

    @asynccontextmanager
    async def read_session(self) -> AsyncIterator[AsyncSession]:
        async with self._read_sessions() as session:
            yield session

    @asynccontextmanager
    async def write_session(self) -> AsyncIterator[AsyncSession]:
        """The single writer path: serialised, ``BEGIN IMMEDIATE``, commit on success."""
        async with self._write_lock, self._write_sessions() as session, session.begin():
            yield session

    async def dispose(self) -> None:
        await self.reader.dispose()
        await self.writer.dispose()
