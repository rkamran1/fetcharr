import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import Settings
from app.db.registry import metadata

config = context.config
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)

target_metadata = metadata


def _database_url() -> str:
    return config.attributes.get("database_url") or Settings().database_url


def _include_name(name: str | None, type_: str, _parent_names: object) -> bool:
    """The history search index (revision 0009) and its FTS5 shadow tables aren't models."""
    return not (type_ == "table" and name is not None and name.startswith("jobs_fts"))


def _run_migrations(connection: Connection) -> None:
    # render_as_batch: SQLite can't ALTER most things in place; batch mode recreates tables.
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,
        include_name=_include_name,
    )
    with context.begin_transaction():
        context.run_migrations()


async def _run_async_migrations() -> None:
    engine = create_async_engine(_database_url())
    async with engine.connect() as connection:
        await connection.run_sync(_run_migrations)
    await engine.dispose()


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(_run_async_migrations())
