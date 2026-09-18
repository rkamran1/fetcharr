"""Server-side sessions (requirements §9): a random id in an HttpOnly cookie, 30 days, sliding."""

import secrets
from datetime import timedelta

from fastapi import Request, Response

from app.db.models import AuthSession, utcnow

COOKIE_NAME = "fetcharr_session"
SESSION_LIFETIME = timedelta(days=30)
# The sliding expiry is written at most once per hour, to spare the database.
SLIDE_INTERVAL = timedelta(hours=1)


def new_session(request: Request) -> AuthSession:
    now = utcnow()
    return AuthSession(
        id=secrets.token_urlsafe(32),
        created_at=now,
        expires_at=now + SESSION_LIFETIME,
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )


def needs_slide(session: AuthSession) -> bool:
    return session.expires_at < utcnow() + SESSION_LIFETIME - SLIDE_INTERVAL


def set_session_cookie(response: Response, session_id: str, *, secure: bool) -> None:
    response.set_cookie(
        COOKIE_NAME,
        session_id,
        max_age=int(SESSION_LIFETIME.total_seconds()),
        path="/",
        secure=secure,
        httponly=True,
        samesite="lax",
    )


def clear_session_cookie(response: Response, *, secure: bool) -> None:
    response.delete_cookie(COOKIE_NAME, path="/", secure=secure, httponly=True, samesite="lax")
