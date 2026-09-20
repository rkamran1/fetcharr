"""The Fernet key and the secrets it protects (requirements §8, AC11)."""

import stat
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from app.settings.utils import KEY_MODE, SecretKeyError, decrypt, encrypt, load_secret_key


def test_a_generated_key_file_is_private_and_reused(tmp_path: Path) -> None:
    path = tmp_path / "config" / "secret.key"

    first = load_secret_key(None, path)
    second = load_secret_key(None, path)

    assert first == second == path.read_bytes()
    assert stat.S_IMODE(path.stat().st_mode) == KEY_MODE == 0o600
    assert decrypt(encrypt("hunter2", first), second) == "hunter2"


def test_the_env_secret_key_wins(tmp_path: Path) -> None:
    path = tmp_path / "secret.key"
    key = Fernet.generate_key().decode()

    loaded = load_secret_key(f" {key} ", path)

    assert loaded == key.encode()
    assert not path.exists()


def test_an_invalid_key_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "secret.key"
    path.write_bytes(b"not a fernet key")

    with pytest.raises(SecretKeyError, match="SECRET_KEY"):
        load_secret_key("also not a key", tmp_path / "unused.key")
    with pytest.raises(SecretKeyError, match=str(path)):
        load_secret_key(None, path)


def test_a_token_from_another_key_does_not_decrypt() -> None:
    token = encrypt("hunter2", Fernet.generate_key())

    assert decrypt(token, Fernet.generate_key()) is None
    assert decrypt("not a token at all", Fernet.generate_key()) is None
