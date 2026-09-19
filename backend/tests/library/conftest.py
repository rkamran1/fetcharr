import shutil
import subprocess
from pathlib import Path

import pytest

SIZES = {
    "landscape": (1920, 1080),
    "vertical": (1080, 1920),
    "qhd": (2560, 1440),
    "uhd": (3840, 2160),
    "hd": (1280, 720),
    "small": (640, 360),
}


def _ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


@pytest.fixture(scope="session")
def media(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """Tiny real media files generated with ffmpeg lavfi (one per resolution + audio only)."""
    root = tmp_path_factory.mktemp("media")
    files: dict[str, Path] = {}
    for name, (width, height) in SIZES.items():
        files[name] = root / f"{name}.mkv"
        _ffmpeg(
            "-f",
            "lavfi",
            "-i",
            f"testsrc=size={width}x{height}:rate=1:duration=1",
            "-f",
            "lavfi",
            "-i",
            "sine=duration=1",
            "-c:v",
            "mpeg4",
            "-c:a",
            "aac",
            "-shortest",
            str(files[name]),
        )
    files["audio"] = root / "audio.mka"
    _ffmpeg("-f", "lavfi", "-i", "sine=duration=1", "-c:a", "aac", str(files["audio"]))
    files["garbage"] = root / "garbage.mkv"
    files["garbage"].write_bytes(b"not a video" * 100)
    return files


@pytest.fixture
def job_dir(tmp_path: Path) -> Path:
    path = tmp_path / "data" / "incomplete" / "job-1"
    path.mkdir(parents=True)
    return path


@pytest.fixture
def video(media: dict[str, Path], job_dir: Path) -> Path:
    """A 1080p mkv in the job dir, as yt-dlp would leave it."""
    return Path(shutil.copy(media["landscape"], job_dir / "video.mkv"))
