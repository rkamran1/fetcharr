"""Auth helpers: password/API-key hashing, the session cookie, login rate limiting.

argon2id is deliberately CPU-heavy, so hashing and verification always run in a worker
thread (requirements §3.2). API keys are random 256-bit tokens, for which a fast SHA-256
is sufficient; argon2 would cost ~100 ms on every API-key request.

Sessions (requirements §9) are a random id in an HttpOnly cookie, 30 days, sliding.

Login rate limiting is 5 attempts per minute per client IP, in memory on purpose:
fetcharr runs as a single process (requirements §6.1).
"""

import asyncio
import hashlib
import hmac
import math
import time
from collections import deque
from datetime import datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Response

from app.db.base import utcnow

COOKIE_NAME = "fetcharr_session"
SESSION_LIFETIME = timedelta(days=30)
# The sliding expiry is written at most once per hour, to spare the database.
SLIDE_INTERVAL = timedelta(hours=1)

LOGIN_ATTEMPTS = 5
WINDOW_SECONDS = 60.0

_hasher = PasswordHasher()


async def hash_password(password: str) -> str:
    return await asyncio.to_thread(_hasher.hash, password)


def _verify(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


async def verify_password(password_hash: str, password: str) -> bool:
    return await asyncio.to_thread(_verify, password_hash, password)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def token_matches(token: str, token_hash: str | None) -> bool:
    return token_hash is not None and hmac.compare_digest(hash_token(token), token_hash)


def needs_slide(expires_at: datetime) -> bool:
    return expires_at < utcnow() + SESSION_LIFETIME - SLIDE_INTERVAL


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


class LoginRateLimiter:
    def __init__(self) -> None:
        self._attempts: dict[str, deque[float]] = {}

    def hit(self, key: str) -> int | None:
        """Record an attempt. Returns ``None`` if allowed, else the seconds to wait."""
        now = time.monotonic()
        cutoff = now - WINDOW_SECONDS
        for stale in [k for k, a in self._attempts.items() if a[-1] <= cutoff]:
            del self._attempts[stale]
        attempts = self._attempts.setdefault(key, deque())
        while attempts and attempts[0] <= cutoff:
            attempts.popleft()
        if len(attempts) >= LOGIN_ATTEMPTS:
            return max(1, math.ceil(attempts[0] - cutoff))
        attempts.append(now)
        return None
