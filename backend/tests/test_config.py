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


def test_secret_and_radarr_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("SECRET_KEY", "SECRET_KEY_FILE", "RADARR_URL", "RADARR_API_KEY"):
        monkeypatch.delenv(name, raising=False)

    settings = Settings()

    assert settings.secret_key is None
    assert settings.secret_key_file == Path("/config/secret.key")
    assert settings.radarr_url is None
    assert settings.radarr_api_key is None

    monkeypatch.setenv("SECRET_KEY", "a-key")
    monkeypatch.setenv("SECRET_KEY_FILE", "/run/secrets/fetcharr")
    monkeypatch.setenv("RADARR_URL", "http://radarr:7878")
    monkeypatch.setenv("RADARR_API_KEY", "abc")

    settings = Settings()

    assert settings.secret_key == "a-key"
    assert settings.secret_key_file == Path("/run/secrets/fetcharr")
    assert settings.radarr_url == "http://radarr:7878"
    assert settings.radarr_api_key == "abc"
