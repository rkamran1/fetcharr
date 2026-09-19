from typing import Any

import pytest
from pydantic import ValidationError

from app.ytdlp.options import DownloadOptions


def test_defaults() -> None:
    options = DownloadOptions(quality="720p")

    assert options.container == "mkv"
    assert options.fragments == "auto"
    assert options.use_aria2c == "auto"
    assert options.retries == 5


def test_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        DownloadOptions.model_validate({"quality": "720p", "exec": "rm -rf /"})


@pytest.mark.parametrize(
    "overrides",
    [
        {"fragments": 0},
        {"fragments": 17},
        {"container": "avi"},
        {"quality": "999p"},
        {"use_aria2c": "maybe"},
        {"retries": -1},
    ],
    ids=lambda o: "-".join(f"{k}={v}" for k, v in o.items()),
)
def test_rejects_invalid_values(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        DownloadOptions.model_validate({"quality": "720p", **overrides})
