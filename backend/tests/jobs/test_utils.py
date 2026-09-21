from pathlib import Path

from app.integrations.arr import Rejection
from app.jobs.utils import as_stream_type, explain_rejection, is_inside


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
