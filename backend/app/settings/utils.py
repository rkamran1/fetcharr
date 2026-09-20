"""The Fernet key and the encrypt/decrypt helpers for secrets at rest (requirements §8).

Pure helpers plus one file read: everything here is blocking, so the caller runs it through
``asyncio.to_thread`` (§3.2). The key is loaded once at startup, never per request.
"""

import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

#: The generated key file is readable by its owner only.
KEY_MODE = 0o600


class SecretKeyError(Exception):
    """The configured key is missing or unusable."""


def load_secret_key(secret_key: str | None, secret_key_file: Path) -> bytes:
    """`SECRET_KEY` if it is set, else `SECRET_KEY_FILE`, generating it on first start."""
    if secret_key:
        return _validated(secret_key.strip().encode(), "SECRET_KEY")
    if secret_key_file.is_file():
        return _validated(secret_key_file.read_bytes().strip(), str(secret_key_file))
    key = Fernet.generate_key()
    secret_key_file.parent.mkdir(parents=True, exist_ok=True)
    # Created unreadable to anyone else before a byte is written; a later chmod is a race.
    descriptor = os.open(secret_key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, KEY_MODE)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(key)
    return key


def encrypt(value: str, key: bytes) -> str:
    return Fernet(key).encrypt(value.encode()).decode()


def decrypt(token: str, key: bytes) -> str | None:
    """The plaintext, or None when the token doesn't belong to this key."""
    try:
        return Fernet(key).decrypt(token.encode()).decode()
    except (InvalidToken, ValueError):
        return None


def _validated(key: bytes, source: str) -> bytes:
    try:
        Fernet(key)
    except (ValueError, TypeError) as error:
        raise SecretKeyError(
            f"{source} is not a valid Fernet key (32 url-safe base64-encoded bytes): {error}"
        ) from error
    return key
