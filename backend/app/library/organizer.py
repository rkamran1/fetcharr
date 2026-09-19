"""Move a finished job from incomplete/<job_id>/ into completed/ (requirements §7.3, §7.4)."""

import asyncio
import errno
import os
import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from app.library.naming import Other, Target, build_path, quality_label, sidecar_name
from app.library.probe import ProbeError, probe

# Written into the job dir before the first move; pins the destination for re-runs (§6.1).
MARKER = "organize_target"
PARTIAL_SUFFIX = ".fetcharr-partial"
REPLACED_DIR = "_replaced"


class CollisionPolicy(StrEnum):
    ASK = "ask"
    REPLACE = "replace"
    KEEP_BOTH = "keep_both"


class OrganizeError(Exception):
    """The job's files can't be organised."""


class InvalidMediaError(OrganizeError):
    """The downloaded file isn't a playable video."""


class PathEscapeError(OrganizeError):
    """The destination would land outside COMPLETED_DIR."""


class CollisionError(OrganizeError):
    """An un-imported file already exists at the destination (policy `ask`)."""

    def __init__(self, existing: Path) -> None:
        super().__init__(f"{existing} already exists")
        self.existing = existing


@dataclass(frozen=True)
class Sidecar:
    path: Path
    lang: str


@dataclass(frozen=True)
class Organized:
    video: Path
    sidecars: tuple[Path, ...]
    size: int


async def organize(
    job_dir: Path,
    video_path: Path,
    sidecars: Sequence[Sidecar],
    target: Target,
    collision_policy: CollisionPolicy,
    *,
    completed_dir: Path,
    incomplete_dir: Path,
) -> Organized:
    """Probe, name and move the job's files. Safe to run again after any crash."""
    destination = await asyncio.to_thread(_read_marker, job_dir)
    first_run = destination is None
    if destination is None:
        try:
            media = await probe(video_path)
        except ProbeError as error:
            raise InvalidMediaError(str(error)) from error
        if not media.has_video or media.duration <= 0:
            raise InvalidMediaError(f"{video_path.name} has no video stream or no duration")
        quality = quality_label(media.width, media.height)
        try:
            destination = completed_dir / build_path(target, quality, video_path.suffix)
        except ValueError as error:
            raise OrganizeError(str(error)) from error
    policy = CollisionPolicy.KEEP_BOTH if isinstance(target, Other) else collision_policy
    # All filesystem work (resolving, copying, fsync) runs off the event loop (§3.2).
    return await asyncio.to_thread(
        _organize_files,
        job_dir,
        video_path,
        sidecars,
        destination,
        first_run,
        policy,
        completed_dir,
        incomplete_dir,
    )


def is_organized(job_dir: Path, video_path: Path, completed_path: Path | None = None) -> bool:
    """The organize step's done-check: the video is at its destination and gone from the job."""
    destination = completed_path or _read_marker(job_dir)
    return destination is not None and destination.is_file() and not video_path.exists()


def _read_marker(job_dir: Path) -> Path | None:
    marker = job_dir / MARKER
    return Path(marker.read_text()) if marker.is_file() else None


def _write_marker(job_dir: Path, destination: Path) -> None:
    temporary = job_dir / f"{MARKER}.tmp"
    temporary.write_text(str(destination))
    os.replace(temporary, job_dir / MARKER)


def _organize_files(
    job_dir: Path,
    video_path: Path,
    sidecars: Sequence[Sidecar],
    destination: Path,
    first_run: bool,
    policy: CollisionPolicy,
    completed_dir: Path,
    incomplete_dir: Path,
) -> Organized:
    destination = _guard(destination, completed_dir)
    if first_run and destination.exists():
        destination = _resolve_collision(destination, policy, job_dir, incomplete_dir)
    destination.parent.mkdir(parents=True, exist_ok=True)
    _write_marker(job_dir, destination)

    # Sidecars first, video last: arr must never see a video without its subtitles.
    moved = []
    for sidecar in sidecars:
        name = sidecar_name(destination.name, sidecar.lang, sidecar.path.suffix)
        moved.append(_move(sidecar.path, destination.with_name(name)))
    _move(video_path, destination)
    return Organized(destination, tuple(moved), destination.stat().st_size)


def _guard(destination: Path, completed_dir: Path) -> Path:
    parent = destination.parent.resolve()
    if not parent.is_relative_to(completed_dir.resolve()):
        raise PathEscapeError(f"{destination} is outside {completed_dir}")
    return parent / destination.name


def _resolve_collision(
    destination: Path, policy: CollisionPolicy, job_dir: Path, incomplete_dir: Path
) -> Path:
    match policy:
        case CollisionPolicy.ASK:
            raise CollisionError(destination)
        case CollisionPolicy.REPLACE:
            aside = incomplete_dir / REPLACED_DIR / job_dir.name
            aside.mkdir(parents=True, exist_ok=True)
            for existing in destination.parent.iterdir():
                if existing.name.startswith(f"{destination.stem}."):
                    _move(existing, aside / existing.name)
            return destination
        case CollisionPolicy.KEEP_BOTH:
            number = 1
            while (candidate := _numbered(destination, number)).exists():
                number += 1
            return candidate


def _numbered(destination: Path, number: int) -> Path:
    return destination.with_name(f"{destination.stem} ({number}){destination.suffix}")


def _move(source: Path, destination: Path) -> Path:
    partial = destination.with_name(f".{destination.name}{PARTIAL_SUFFIX}")
    partial.unlink(missing_ok=True)
    if not source.exists():
        if destination.exists():
            return destination  # moved by an earlier run
        raise FileNotFoundError(errno.ENOENT, "nothing to move", str(source))
    if destination.exists() and destination.stat().st_size == source.stat().st_size:
        source.unlink()  # an earlier run got as far as the destination
        return destination
    try:
        os.rename(source, destination)
    except OSError as error:
        if error.errno != errno.EXDEV:
            raise
        _copy(source, partial)
        os.rename(partial, destination)
        source.unlink()
    return destination


def _copy(source: Path, partial: Path) -> None:
    with source.open("rb") as reader, partial.open("wb") as writer:
        shutil.copyfileobj(reader, writer, 1024 * 1024)
        writer.flush()
        os.fsync(writer.fileno())
