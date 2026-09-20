"""The startup path self-test (requirements §7.6)."""

import os
from dataclasses import dataclass
from pathlib import Path

PROBE_NAME = ".fetcharr-probe"
#: The folders every download passes through; they must all be writable and on one volume.
COMPLETED_SUBFOLDERS = ("movies", "tv-shows", "other")


@dataclass(frozen=True)
class PathCheck:
    path: str
    ok: bool
    error: str | None = None


@dataclass(frozen=True)
class PathReport:
    ok: bool
    same_filesystem: bool
    checks: tuple[PathCheck, ...]


def check_paths(completed_dir: Path, incomplete_dir: Path) -> PathReport:
    """Create the folders, write-rename-delete a probe file in each, and compare st_dev."""
    folders = [incomplete_dir, *(completed_dir / name for name in COMPLETED_SUBFOLDERS)]
    checks: list[PathCheck] = []
    devices: set[int] = set()

    for folder in folders:
        try:
            folder.mkdir(parents=True, exist_ok=True)
            _probe(folder)
            devices.add(folder.stat().st_dev)
            checks.append(PathCheck(path=str(folder), ok=True))
        except OSError as error:
            checks.append(PathCheck(path=str(folder), ok=False, error=str(error)))

    same_filesystem = len(devices) <= 1
    return PathReport(
        ok=all(check.ok for check in checks) and same_filesystem,
        same_filesystem=same_filesystem,
        checks=tuple(checks),
    )


def _probe(folder: Path) -> None:
    probe = folder / PROBE_NAME
    renamed = folder / f"{PROBE_NAME}.moved"
    probe.write_bytes(b"fetcharr")
    os.replace(probe, renamed)
    renamed.unlink()
