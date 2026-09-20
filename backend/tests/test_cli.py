import asyncio
from collections.abc import AsyncIterator, Iterator

import pytest
from sqlalchemy import select

from app import cli
from app.auth.models import Account, AuthSession
from app.auth.utils import SESSION_LIFETIME, hash_password, verify_password
from app.db.base import utcnow
from app.db.session import Database

OLD_PASSWORD = "old password 1"
NEW_PASSWORD = "new password 2"


@pytest.fixture
async def db(migrated_db_url: str, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Database]:
    monkeypatch.setenv("DATABASE_URL", migrated_db_url)
    database = Database(migrated_db_url)
    yield database
    await database.dispose()


async def _seed_account(db: Database) -> None:
    password_hash = await hash_password(OLD_PASSWORD)
    async with db.write_session() as session:
        session.add(Account(id=1, username="owner", password_hash=password_hash))
        for session_id in ("a", "b"):
            session.add(AuthSession(id=session_id, expires_at=utcnow() + SESSION_LIFETIME))


def _answers(monkeypatch: pytest.MonkeyPatch, *answers: str) -> None:
    replies: Iterator[str] = iter(answers)
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": next(replies))


async def _state(db: Database) -> tuple[Account | None, list[AuthSession]]:
    async with db.read_session() as session:
        account = await session.get(Account, 1)
        sessions = list((await session.scalars(select(AuthSession))).all())
    return account, sessions


async def _run(*argv: str) -> int:
    # cli.main calls asyncio.run(), so it runs on its own thread, as it does in the container.
    return await asyncio.to_thread(cli.main, list(argv))


async def test_reset_password_sets_password_and_clears_sessions(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _seed_account(db)
    _answers(monkeypatch, NEW_PASSWORD, NEW_PASSWORD)

    code = await _run("reset-password")

    account, sessions = await _state(db)
    assert code == 0
    assert account is not None
    assert await verify_password(account.password_hash, NEW_PASSWORD)
    assert not await verify_password(account.password_hash, OLD_PASSWORD)
    assert sessions == []


async def test_reset_password_mismatch_exits_nonzero(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _seed_account(db)
    _answers(monkeypatch, NEW_PASSWORD, "something else")

    code = await _run("reset-password")

    account, sessions = await _state(db)
    assert code == 1
    assert account is not None
    assert await verify_password(account.password_hash, OLD_PASSWORD)
    assert len(sessions) == 2


async def test_reset_password_without_account_exits_nonzero(
    db: Database, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _answers(monkeypatch)

    code = await _run("reset-password")

    assert code == 1
    assert "No account yet" in capsys.readouterr().err
