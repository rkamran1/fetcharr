"""Command-line tools run inside the container: ``fetcharr reset-password``."""

import argparse
import asyncio
import getpass
import sys

from sqlalchemy import delete, update

from app.auth.passwords import hash_password
from app.config import Settings
from app.db.models import Account, AuthSession
from app.db.session import Database

MIN_PASSWORD_LENGTH = 8


async def _reset_password(settings: Settings) -> int:
    db = Database(settings.database_url)
    try:
        async with db.read_session() as session:
            account = await session.get(Account, 1)
        if account is None:
            print("No account yet: finish the setup in the web UI first.", file=sys.stderr)
            return 1
        password = await asyncio.to_thread(getpass.getpass, "New password: ")
        repeated = await asyncio.to_thread(getpass.getpass, "Repeat new password: ")
        if password != repeated:
            print("Passwords do not match; nothing changed.", file=sys.stderr)
            return 1
        if len(password) < MIN_PASSWORD_LENGTH:
            print(
                f"Password must be at least {MIN_PASSWORD_LENGTH} characters; nothing changed.",
                file=sys.stderr,
            )
            return 1
        password_hash = await hash_password(password)
        async with db.write_session() as session:
            await session.execute(update(Account).values(password_hash=password_hash))
            await session.execute(delete(AuthSession))
        print(f"Password for '{account.username}' reset; all sessions were signed out.")
        return 0
    finally:
        await db.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fetcharr")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("reset-password", help="set a new password and sign out every session")
    parser.parse_args(argv)
    return asyncio.run(_reset_password(Settings()))


if __name__ == "__main__":
    sys.exit(main())
