"""Small pure helpers for the jobs domain."""

import shutil
from datetime import datetime, timedelta
from pathlib import Path

from app.integrations.arr import Rejection
from app.ytdlp.stream import StreamType


def as_stream_type(value: str | None) -> StreamType:
    """A stored stream type, falling back to `http` (the script's default behaviour)."""
    match value:
        case "hls" | "dash" | "http":
            return value
        case _:
            return "http"


def is_inside(path: Path, *roots: Path) -> bool:
    """True when `path` resolves inside one of the roots (§7.4 path guard)."""
    resolved = path.resolve()
    return any(resolved.is_relative_to(root.resolve()) for root in roots)


#: Radarr's and Sonarr's one-word verdict for a file far shorter than what it should be.
SAMPLE = "Sample"


def explain_rejection(rejection: Rejection, app: str, file_seconds: float | None) -> str | None:
    """A sentence for the rejections that are one cryptic word; None for the rest (§7.5).

    The app's own reasons are kept verbatim next to this. Only what fetcharr can measure is
    added: the file's real length against the runtime the app expects.
    """
    if rejection.reason != SAMPLE:
        return None
    what = "episode" if app == "Sonarr" else "movie"
    advice = "Pick the full-length video, or download clips and trailers as Other."
    if file_seconds and rejection.runtime_minutes:
        subject = rejection.title or f"the {what}"
        return (
            f"the file is {_clock(file_seconds)} long but {subject} runs "
            f"{rejection.runtime_minutes} min, so {app} takes it for a sample or trailer, "
            f"not the {what} itself. {advice}"
        )
    return f"{app} takes the file for a sample: it is far shorter than the {what}. {advice}"


def _clock(seconds: float) -> str:
    """`2:04`, or `1:02:03` past the hour: how long a video is, the way players show it."""
    total = round(seconds)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


#: The folder replaced files are parked in before the sweep purges them (§7.3).
REPLACED = "_replaced"


def next_run_at(now: datetime, hour: int) -> datetime:
    """The next time it is `hour` o'clock in `now`'s own timezone (the container's TZ)."""
    today = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    return today if today > now else today + timedelta(days=1)


def sweep_incomplete(incomplete_dir: Path, keep: set[str], cutoff: float) -> list[Path]:
    """Delete stale job folders, leaving `keep`'s folders and anything newer than `cutoff`.

    `keep` holds the ids of the jobs that still need their folder: everything else in
    `incomplete/` is a failed or cancelled job, or an orphan with no row at all (§6).
    Blocking: the caller runs it in a thread.
    """
    removed: list[Path] = []
    if not incomplete_dir.is_dir():
        return removed
    for entry in sorted(incomplete_dir.iterdir()):
        if entry.name == REPLACED:
            removed.extend(_purge(entry, cutoff, incomplete_dir))
            continue
        if not entry.is_dir() or entry.name in keep:
            continue
        removed.extend(_remove(entry, cutoff, incomplete_dir))
    return removed


def _purge(replaced: Path, cutoff: float, root: Path) -> list[Path]:
    if not replaced.is_dir():
        return []
    removed: list[Path] = []
    for entry in sorted(replaced.iterdir()):
        removed.extend(_remove(entry, cutoff, root))
    return removed


def _remove(entry: Path, cutoff: float, root: Path) -> list[Path]:
    """Remove one folder or file, but never one that resolves outside `incomplete/`."""
    if entry.stat().st_mtime >= cutoff or not is_inside(entry, root):
        return []
    if entry.is_dir() and not entry.is_symlink():
        shutil.rmtree(entry, ignore_errors=True)
    else:
        entry.unlink(missing_ok=True)
    return [entry]
