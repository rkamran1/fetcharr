from pathlib import Path

import pytest

from app.config import Settings


def test_path_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("COMPLETED_DIR", raising=False)
    monkeypatch.delenv("INCOMPLETE_DIR", raising=False)

    settings = Settings()

    assert settings.completed_dir == Path("/web-downloads/completed")
    assert settings.incomplete_dir == Path("/web-downloads/incomplete")

    monkeypatch.setenv("COMPLETED_DIR", "/srv/done")
    monkeypatch.setenv("INCOMPLETE_DIR", "/srv/work")

    settings = Settings()

    assert settings.completed_dir == Path("/srv/done")
    assert settings.incomplete_dir == Path("/srv/work")
