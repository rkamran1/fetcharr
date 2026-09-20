import shutil
from pathlib import Path

import pytest


@pytest.fixture
def job_dir(tmp_path: Path) -> Path:
    path = tmp_path / "data" / "incomplete" / "job-1"
    path.mkdir(parents=True)
    return path


@pytest.fixture
def video(media: dict[str, Path], job_dir: Path) -> Path:
    """A 1080p mkv in the job dir, as yt-dlp would leave it."""
    return Path(shutil.copy(media["landscape"], job_dir / "video.mkv"))
