"""Small pure helpers for the jobs domain."""

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
