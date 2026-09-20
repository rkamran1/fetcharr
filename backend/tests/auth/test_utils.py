import time

import pytest
from argon2 import PasswordHasher

from app.auth import utils
from app.auth.utils import hash_password, verify_password


class _SlowHasher(PasswordHasher):
    """Blocks for 200 ms: the loop guard fails the test if this runs on the event loop."""

    def hash(self, password: str | bytes, *, salt: bytes | None = None) -> str:
        time.sleep(0.2)
        return super().hash(password, salt=salt)

    def verify(self, hash: str | bytes, password: str | bytes):
        time.sleep(0.2)
        return super().verify(hash, password)


async def test_hash_and_verify_run_off_the_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(utils, "_hasher", _SlowHasher())

    password_hash = await hash_password("correct horse battery")

    assert password_hash.startswith("$argon2id$")
    assert await verify_password(password_hash, "correct horse battery") is True
    assert await verify_password(password_hash, "wrong") is False
    assert await verify_password("not-a-hash", "wrong") is False
