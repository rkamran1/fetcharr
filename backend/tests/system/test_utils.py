"""The startup path self-test (requirements §7.6)."""

import os
from pathlib import Path

import pytest

from app.system.utils import COMPLETED_SUBFOLDERS, check_paths


def test_all_paths_ok(tmp_path: Path) -> None:
    completed = tmp_path / "completed"
    incomplete = tmp_path / "incomplete"

    report = check_paths(completed, incomplete)

    assert report.ok is True
    assert report.same_filesystem is True
    assert [check.path for check in report.checks] == [
        str(incomplete),
        *(str(completed / name) for name in COMPLETED_SUBFOLDERS),
    ]
    # The folders are created, and the probe file is cleaned up again.
    assert all(Path(check.path).is_dir() for check in report.checks)
    assert list(incomplete.iterdir()) == []


def test_read_only_completed_subfolder_is_reported(tmp_path: Path) -> None:
    completed = tmp_path / "completed"
    (completed / "other").mkdir(parents=True)
    (completed / "other").chmod(0o500)
    try:
        report = check_paths(completed, tmp_path / "incomplete")
    finally:
        (completed / "other").chmod(0o700)

    assert report.ok is False
    failed = [check for check in report.checks if not check.ok]
    assert [check.path for check in failed] == [str(completed / "other")]
    assert failed[0].error


def test_different_filesystems_are_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    completed = tmp_path / "completed"
    incomplete = tmp_path / "incomplete"
    real_stat = Path.stat

    def fake_stat(self: Path, *args: object, **kwargs: object) -> os.stat_result:
        result = real_stat(self, *args, **kwargs)
        if self == incomplete:
            values = list(result)
            values[2] = result.st_dev + 1  # st_dev
            return os.stat_result(values)
        return result

    monkeypatch.setattr(Path, "stat", fake_stat)

    report = check_paths(completed, incomplete)

    assert report.same_filesystem is False
    assert report.ok is False
    assert all(check.ok for check in report.checks)
