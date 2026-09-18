"""Authentication dependencies for the ``/api`` routes (requirements §9).

``require_auth`` accepts a valid ``X-Api-Key`` header or a valid session cookie. Requests
authenticated by cookie that change state must come from the same origin (CSRF check);
API-key requests are exempt.
"""

from dataclasses import dataclass
from urllib.parse import urlsplit

from fastapi import HTTPException, Request, Response
from sqlalchemy import update

from app.auth.passwords import token_matches
from app.auth.sessions import (
    COOKIE_NAME,
    SESSION_LIFETIME,
    needs_slide,
    set_session_cookie,
)
from app.db.models import Account, AuthSession, utcnow

STATE_CHANGING = frozenset({"POST", "PUT", "PATCH", "DELETE"})


@dataclass(frozen=True)
class Auth:
    session_id: str | None  # None when authenticated with the API key


def _unauthorized() -> HTTPException:
    return HTTPException(status_code=401, detail="Not authenticated")


def _verify_origin(request: Request) -> None:
    if request.method not in STATE_CHANGING:
        return
    source = request.headers.get("origin") or request.headers.get("referer")
    host = request.headers.get("host")
    if not source or not host or urlsplit(source).netloc != host:
        raise HTTPException(status_code=403, detail="Origin not allowed")


async def check_origin(request: Request) -> None:
    """For the public routes: apply the Origin check whenever a session cookie is sent."""
    if COOKIE_NAME in request.cookies:
        _verify_origin(request)


async def require_auth(request: Request, response: Response) -> Auth:
    db = request.app.state.db
    api_key = request.headers.get("x-api-key")
    if api_key is not None:
        async with db.read_session() as session:
            account = await session.get(Account, 1)
        if account is None or not token_matches(api_key, account.api_key_hash):
            raise _unauthorized()
        return Auth(session_id=None)

    session_id = request.cookies.get(COOKIE_NAME)
    if not session_id:
        raise _unauthorized()
    async with db.read_session() as session:
        auth_session = await session.get(AuthSession, session_id)
    if auth_session is None or auth_session.expires_at <= utcnow():
        raise _unauthorized()
    _verify_origin(request)
    if needs_slide(auth_session):
        async with db.write_session() as session:
            await session.execute(
                update(AuthSession)
                .where(AuthSession.id == session_id)
                .values(expires_at=utcnow() + SESSION_LIFETIME)
            )
        set_session_cookie(response, session_id, secure=request.app.state.settings.cookie_secure)
    return Auth(session_id=session_id)
