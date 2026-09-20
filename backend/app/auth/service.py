"""The single account, its sessions and API key (requirements §9)."""

import secrets

from sqlalchemy import delete, update

from app.auth.exceptions import InvalidCredentials, RateLimited, SetupAlreadyComplete, WrongPassword
from app.auth.models import Account, AuthSession
from app.auth.utils import (
    SESSION_LIFETIME,
    LoginRateLimiter,
    hash_password,
    hash_token,
    token_matches,
    verify_password,
)
from app.db.base import utcnow
from app.db.session import Database


def _new_session(ip: str | None, user_agent: str | None) -> AuthSession:
    now = utcnow()
    return AuthSession(
        id=secrets.token_urlsafe(32),
        created_at=now,
        expires_at=now + SESSION_LIFETIME,
        ip=ip,
        user_agent=user_agent,
    )


class AuthService:
    def __init__(self, db: Database, login_limiter: LoginRateLimiter) -> None:
        self.db = db
        self.login_limiter = login_limiter

    async def _account(self) -> Account | None:
        async with self.db.read_session() as session:
            return await session.get(Account, 1)

    async def username(self) -> str | None:
        """The account's username, or None before setup."""
        account = await self._account()
        return account.username if account is not None else None

    async def setup(
        self, username: str, password: str, ip: str | None, user_agent: str | None
    ) -> str:
        """Create the account and sign it in; returns the new session id."""
        password_hash = await hash_password(password)
        auth_session = _new_session(ip, user_agent)
        async with self.db.write_session() as session:
            if await session.get(Account, 1) is not None:
                raise SetupAlreadyComplete
            session.add(
                Account(
                    id=1,
                    username=username,
                    password_hash=password_hash,
                    last_login_at=auth_session.created_at,
                )
            )
            session.add(auth_session)
        return auth_session.id

    async def login(
        self, username: str, password: str, client_ip: str | None, user_agent: str | None
    ) -> tuple[str, str]:
        """Check the credentials; returns (username, new session id)."""
        retry_after = self.login_limiter.hit(client_ip or "unknown")
        if retry_after is not None:
            raise RateLimited(retry_after)
        account = await self._account()
        if (
            account is None
            or username.strip() != account.username
            or not await verify_password(account.password_hash, password)
        ):
            raise InvalidCredentials
        auth_session = _new_session(client_ip, user_agent)
        async with self.db.write_session() as session:
            await session.execute(update(Account).values(last_login_at=auth_session.created_at))
            session.add(auth_session)
        return account.username, auth_session.id

    async def logout(self, session_id: str | None) -> None:
        if session_id is not None:
            async with self.db.write_session() as session:
                await session.execute(delete(AuthSession).where(AuthSession.id == session_id))

    async def change_password(
        self, current_password: str, new_password: str, keep_session_id: str | None
    ) -> None:
        """Set a new password and sign out every other session."""
        account = await self._account()
        if account is None or not await verify_password(account.password_hash, current_password):
            raise WrongPassword
        password_hash = await hash_password(new_password)
        others = delete(AuthSession)
        if keep_session_id is not None:
            others = others.where(AuthSession.id != keep_session_id)
        async with self.db.write_session() as session:
            await session.execute(update(Account).values(password_hash=password_hash))
            await session.execute(others)

    async def reset_password(self, password: str) -> None:
        """Set a new password and sign out every session (``fetcharr reset-password``)."""
        password_hash = await hash_password(password)
        async with self.db.write_session() as session:
            await session.execute(update(Account).values(password_hash=password_hash))
            await session.execute(delete(AuthSession))

    async def regenerate_api_key(self) -> str:
        api_key = secrets.token_urlsafe(32)
        async with self.db.write_session() as session:
            await session.execute(update(Account).values(api_key_hash=hash_token(api_key)))
        return api_key

    async def api_key_valid(self, api_key: str) -> bool:
        account = await self._account()
        return account is not None and token_matches(api_key, account.api_key_hash)

    async def valid_session(self, session_id: str) -> AuthSession | None:
        """The session, if it exists and hasn't expired."""
        async with self.db.read_session() as session:
            auth_session = await session.get(AuthSession, session_id)
        if auth_session is None or auth_session.expires_at <= utcnow():
            return None
        return auth_session

    async def slide_session(self, session_id: str) -> None:
        async with self.db.write_session() as session:
            await session.execute(
                update(AuthSession)
                .where(AuthSession.id == session_id)
                .values(expires_at=utcnow() + SESSION_LIFETIME)
            )
