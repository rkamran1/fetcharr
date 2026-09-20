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


def test_pipeline_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MAX_CONCURRENT_DOWNLOADS", raising=False)
    monkeypatch.delenv("AUTO_RESUME", raising=False)

    settings = Settings()

    assert settings.max_concurrent_downloads == 2
    assert settings.auto_resume is True

    monkeypatch.setenv("MAX_CONCURRENT_DOWNLOADS", "4")
    monkeypatch.setenv("AUTO_RESUME", "false")

    settings = Settings()

    assert settings.max_concurrent_downloads == 4
    assert settings.auto_resume is False
