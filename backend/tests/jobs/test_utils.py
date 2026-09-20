from pathlib import Path

from app.jobs.utils import as_stream_type, is_inside


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
