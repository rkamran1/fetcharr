import os
import time
from datetime import UTC, datetime
from pathlib import Path

from app.integrations.arr import Rejection
from app.jobs.utils import (
    as_stream_type,
    explain_rejection,
    is_inside,
    next_run_at,
    sweep_incomplete,
)


def test_as_stream_type_falls_back_to_http() -> None:
    assert [as_stream_type(value) for value in ("hls", "dash", "http")] == ["hls", "dash", "http"]
    assert as_stream_type(None) == "http"
    assert as_stream_type("nonsense") == "http"


def test_is_inside_resolves_before_comparing(tmp_path: Path) -> None:
    completed = tmp_path / "completed"
    (completed / "other").mkdir(parents=True)
    incomplete = tmp_path / "incomplete"
    incomplete.mkdir()

    assert is_inside(completed / "other" / "video.mkv", completed, incomplete)
    assert is_inside(incomplete / "job-1", completed, incomplete)
    assert not is_inside(tmp_path / "elsewhere.mkv", completed, incomplete)
    # A path that climbs back out is resolved first (§7.4).
    assert not is_inside(completed / ".." / "elsewhere.mkv", completed, incomplete)


# -------------------------------------- AC16: a one-word rejection, put in context


def test_a_sample_rejection_is_explained_with_both_lengths() -> None:
    """The real case from review: a 2-minute clip filed as an 88-minute movie."""
    sample = Rejection(reason="Sample", permanent=True, runtime_minutes=88, title="Jumper")

    explanation = explain_rejection(sample, "Radarr", 124.528)

    assert explanation == (
        "the file is 2:05 long but Jumper runs 88 min, so Radarr takes it for a sample or "
        "trailer, not the movie itself. Pick the full-length video, or download clips and "
        "trailers as Other."
    )


def test_a_long_file_is_shown_with_hours() -> None:
    sample = Rejection(reason="Sample", permanent=True, runtime_minutes=180, title="Heat")

    assert "1:02:03 long" in (explain_rejection(sample, "Radarr", 3723) or "")


def test_a_sonarr_sample_talks_about_the_episode() -> None:
    sample = Rejection(reason="Sample", permanent=True, runtime_minutes=47, title="Breaking Bad")

    explanation = explain_rejection(sample, "Sonarr", 90) or ""

    assert "Breaking Bad runs 47 min" in explanation
    assert "not the episode itself" in explanation


def test_a_sample_without_a_runtime_is_still_explained() -> None:
    """No runtime from the app, or no length from ffprobe: still say what the word means."""
    sample = Rejection(reason="Sample", permanent=True)

    assert explain_rejection(sample, "Radarr", None) == (
        "Radarr takes the file for a sample: it is far shorter than the movie. "
        "Pick the full-length video, or download clips and trailers as Other."
    )


def test_other_rejections_are_left_as_the_app_said_them() -> None:
    """Every other reason is already a sentence, and is shown verbatim (§7.5)."""
    rejection = Rejection(reason="Not an upgrade for existing movie file(s)", permanent=True)

    assert explain_rejection(rejection, "Radarr", 5000) is None


def _aged(path: Path, days: float) -> Path:
    """A folder or file whose mtime is `days` old, as the sweep reads it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.mkdir() if not path.suffix else path.write_text("x")
    old = time.time() - days * 86_400
    os.utime(path, (old, old))
    return path


CUTOFF_DAYS = 7


def _cutoff() -> float:
    return time.time() - CUTOFF_DAYS * 86_400


def test_next_run_at_is_later_today_when_the_hour_is_still_ahead() -> None:
    now = datetime(2026, 5, 4, 1, 30, tzinfo=UTC)

    assert next_run_at(now, 3) == datetime(2026, 5, 4, 3, 0, tzinfo=UTC)


def test_next_run_at_is_tomorrow_once_the_hour_has_passed() -> None:
    now = datetime(2026, 5, 4, 3, 0, 1, tzinfo=UTC)

    assert next_run_at(now, 3) == datetime(2026, 5, 5, 3, 0, tzinfo=UTC)


def test_sweep_removes_old_failed_and_cancelled_dirs(tmp_path: Path) -> None:
    incomplete = tmp_path / "incomplete"
    failed = _aged(incomplete / "failed-job", 8)
    cancelled = _aged(incomplete / "cancelled-job", 30)

    removed = sweep_incomplete(incomplete, set(), _cutoff())

    assert set(removed) == {failed, cancelled}
    assert not failed.exists() and not cancelled.exists()


def test_sweep_removes_old_orphan_dirs(tmp_path: Path) -> None:
    incomplete = tmp_path / "incomplete"
    orphan = _aged(incomplete / "no-such-job", 9)

    assert sweep_incomplete(incomplete, {"running-job"}, _cutoff()) == [orphan]
    assert not orphan.exists()


def test_sweep_keeps_recent_and_running_dirs(tmp_path: Path) -> None:
    incomplete = tmp_path / "incomplete"
    running = _aged(incomplete / "running-job", 30)
    recent = _aged(incomplete / "recent-job", 1)

    assert sweep_incomplete(incomplete, {"running-job"}, _cutoff()) == []
    assert running.is_dir() and recent.is_dir()


def test_sweep_purges_old_replaced_files(tmp_path: Path) -> None:
    incomplete = tmp_path / "incomplete"
    old_file = _aged(incomplete / "_replaced" / "old.mkv", 8)
    old_dir = _aged(incomplete / "_replaced" / "old-folder", 8)
    kept = _aged(incomplete / "_replaced" / "new.mkv", 1)
    _aged(incomplete / "_replaced", 30)

    removed = sweep_incomplete(incomplete, set(), _cutoff())

    assert set(removed) == {old_file, old_dir}
    assert kept.is_file()
    # The parking folder itself stays, however old it is.
    assert (incomplete / "_replaced").is_dir()


def test_sweep_leaves_completed_alone(tmp_path: Path) -> None:
    incomplete = tmp_path / "incomplete"
    incomplete.mkdir()
    completed = _aged(tmp_path / "completed" / "movies", 400)

    assert sweep_incomplete(incomplete, set(), _cutoff()) == []
    assert completed.is_dir()


def test_sweep_never_follows_a_link_out_of_incomplete(tmp_path: Path) -> None:
    incomplete = tmp_path / "incomplete"
    incomplete.mkdir()
    outside = _aged(tmp_path / "elsewhere", 400)
    link = incomplete / "escape"
    link.symlink_to(outside, target_is_directory=True)

    assert sweep_incomplete(incomplete, set(), _cutoff()) == []
    assert outside.is_dir()


def test_sweep_without_an_incomplete_dir_does_nothing(tmp_path: Path) -> None:
    assert sweep_incomplete(tmp_path / "missing", set(), _cutoff()) == []
