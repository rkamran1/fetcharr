"""Password and API-key hashing.

argon2id is deliberately CPU-heavy, so hashing and verification always run in a worker
thread (requirements §3.2). API keys are random 256-bit tokens, for which a fast SHA-256
is sufficient; argon2 would cost ~100 ms on every API-key request.
"""

import asyncio
import hashlib
import hmac

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

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
