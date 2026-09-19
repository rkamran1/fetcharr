import errno
import os
import threading
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest

from app.library import organizer
from app.library.naming import Episode, Movie, Other, Target
from app.library.organizer import (
    MARKER,
    PARTIAL_SUFFIX,
    CollisionError,
    CollisionPolicy,
    InvalidMediaError,
    Organized,
    OrganizeError,
    PathEscapeError,
    Sidecar,
    is_organized,
    organize,
)
from app.library.probe import ProbeResult

BUNNY = Movie("Big Buck Bunny", 2008)
MOVIE_DIR = "movies/Big Buck Bunny (2008)"
VIDEO = f"{MOVIE_DIR}/Big Buck Bunny (2008) WEBDL-1080p.mkv"
SUB = f"{MOVIE_DIR}/Big Buck Bunny (2008) WEBDL-1080p.en.srt"
VIDEO_1 = f"{MOVIE_DIR}/Big Buck Bunny (2008) WEBDL-1080p (1).mkv"
SUB_1 = f"{MOVIE_DIR}/Big Buck Bunny (2008) WEBDL-1080p (1).en.srt"
SUB_TEXT = b"1\n00:00:00,000 --> 00:00:01,000\nHello\n"
OLD = b"older download"

real_rename = os.rename

Run = Callable[..., Awaitable[Organized]]


def tree(root: Path) -> dict[str, bytes]:
    """Every file under `root` with its content, keyed by its relative POSIX path."""
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def put(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _cross_device(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
    if Path(src).parent != Path(dst).parent:
        raise OSError(errno.EXDEV, os.strerror(errno.EXDEV))
    real_rename(src, dst)


@pytest.fixture
def completed(tmp_path: Path) -> Path:
    path = tmp_path / "data" / "completed"
    path.mkdir(parents=True)
    return path


@pytest.fixture
def incomplete(job_dir: Path) -> Path:
    return job_dir.parent


@pytest.fixture
def content(video: Path) -> bytes:
    return video.read_bytes()


@pytest.fixture
def subtitle(job_dir: Path) -> Sidecar:
    return Sidecar(put(job_dir / "video.en.srt", SUB_TEXT), "en")


@pytest.fixture
def run(job_dir: Path, video: Path, subtitle: Sidecar, completed: Path, incomplete: Path) -> Run:
    async def run(
        target: Target = BUNNY, policy: CollisionPolicy = CollisionPolicy.ASK
    ) -> Organized:
        return await organize(
            job_dir,
            video,
            [subtitle],
            target,
            policy,
            completed_dir=completed,
            incomplete_dir=incomplete,
        )

    return run


@pytest.fixture
def make_job(media: dict[str, Path], incomplete: Path) -> Callable[..., Path]:
    """A second job dir holding a copy of one of the generated media files."""

    def make_job(name: str, fixture: str = "landscape") -> Path:
        return put(incomplete / name / f"video{media[fixture].suffix}", media[fixture].read_bytes())

    return make_job


async def _organize(video: Path, completed: Path, target: Target = BUNNY) -> Organized:
    return await organize(
        video.parent,
        video,
        [],
        target,
        CollisionPolicy.ASK,
        completed_dir=completed,
        incomplete_dir=video.parent.parent,
    )


async def test_moves_sidecars_before_video(
    run: Run, content: bytes, job_dir: Path, completed: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    renames: list[tuple[str, str]] = []

    def spy(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
        renames.append((Path(src).name, Path(dst).name))
        real_rename(src, dst)

    monkeypatch.setattr(os, "rename", spy)

    result = await run()

    assert renames == [("video.en.srt", Path(SUB).name), ("video.mkv", Path(VIDEO).name)]
    assert result == Organized(completed / VIDEO, (completed / SUB,), len(content))
    assert tree(completed) == {SUB: SUB_TEXT, VIDEO: content}
    assert list(tree(job_dir)) == [MARKER]


async def test_cross_device_move_copies_via_partial(
    run: Run, content: bytes, job_dir: Path, completed: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    synced: list[int] = []
    real_fsync = os.fsync

    def spy_fsync(fd: int) -> None:
        synced.append(fd)
        real_fsync(fd)

    monkeypatch.setattr(os, "rename", _cross_device)
    monkeypatch.setattr(os, "fsync", spy_fsync)

    await run()

    assert len(synced) == 2  # one per copied file
    # No `.fetcharr-partial` left behind, and the sources are gone.
    assert tree(completed) == {SUB: SUB_TEXT, VIDEO: content}
    assert list(tree(job_dir)) == [MARKER]


async def test_collision_ask_raises(
    run: Run, content: bytes, job_dir: Path, completed: Path
) -> None:
    existing = put(completed / VIDEO, OLD)

    with pytest.raises(CollisionError) as caught:
        await run(policy=CollisionPolicy.ASK)

    assert caught.value.existing == existing
    assert tree(completed) == {VIDEO: OLD}
    assert tree(job_dir) == {"video.en.srt": SUB_TEXT, "video.mkv": content}


async def test_collision_replace_moves_old_files_aside(
    run: Run, content: bytes, completed: Path, incomplete: Path, job_dir: Path
) -> None:
    put(completed / VIDEO, OLD)
    put(completed / SUB, b"old subtitle")
    put(completed / VIDEO_1, b"keep me")

    result = await run(policy=CollisionPolicy.REPLACE)

    assert result.video == completed / VIDEO
    assert tree(completed) == {SUB: SUB_TEXT, VIDEO_1: b"keep me", VIDEO: content}
    assert tree(incomplete / "_replaced" / job_dir.name) == {
        Path(SUB).name: b"old subtitle",
        Path(VIDEO).name: OLD,
    }


async def test_collision_keep_both_numbers(
    run: Run, make_job: Callable[..., Path], completed: Path
) -> None:
    put(completed / VIDEO, OLD)
    second_video = make_job("job-2")

    first = await run(policy=CollisionPolicy.KEEP_BOTH)
    second = await organize(
        second_video.parent,
        second_video,
        [],
        BUNNY,
        CollisionPolicy.KEEP_BOTH,
        completed_dir=completed,
        incomplete_dir=second_video.parent.parent,
    )

    assert first.video == completed / VIDEO_1
    assert first.sidecars == (completed / SUB_1,)
    assert second.video.name == "Big Buck Bunny (2008) WEBDL-1080p (2).mkv"
    assert tree(completed)[VIDEO] == OLD


async def test_other_always_keeps_both(make_job: Callable[..., Path], completed: Path) -> None:
    name = "other/Some Video Title [dQw4w9WgXcQ]"
    put(completed / f"{name}.mkv", OLD)
    video = make_job("job-other")

    result = await _organize(video, completed, Other("Some Video Title", "dQw4w9WgXcQ"))

    assert result.video == completed / f"{name} (1).mkv"
    assert tree(completed)[f"{name}.mkv"] == OLD


async def test_organize_twice_is_idempotent(
    run: Run, content: bytes, job_dir: Path, completed: Path
) -> None:
    first = await run()
    second = await run()

    assert second == first
    assert tree(completed) == {SUB: SUB_TEXT, VIDEO: content}
    assert list(tree(job_dir)) == [MARKER]


async def test_rerun_after_crash_between_sidecar_and_video(
    run: Run,
    video: Path,
    content: bytes,
    job_dir: Path,
    completed: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    put(completed / VIDEO, OLD)  # forces keep-both, whose ` (1)` must survive the re-run

    def crash_on_video(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
        if Path(src) == video:
            raise RuntimeError("power cut")
        real_rename(src, dst)

    monkeypatch.setattr(os, "rename", crash_on_video)
    with pytest.raises(RuntimeError):
        await run(policy=CollisionPolicy.KEEP_BOTH)
    assert tree(completed) == {SUB_1: SUB_TEXT, VIDEO: OLD}
    assert "video.mkv" in tree(job_dir)

    monkeypatch.setattr(os, "rename", real_rename)
    result = await run(policy=CollisionPolicy.KEEP_BOTH)

    assert result.video == completed / VIDEO_1
    assert tree(completed) == {SUB_1: SUB_TEXT, VIDEO_1: content, VIDEO: OLD}
    assert list(tree(job_dir)) == [MARKER]


async def test_rerun_after_crash_mid_copy_cleans_partial(
    run: Run, content: bytes, job_dir: Path, completed: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_copy = organizer._copy
    partial = f"{MOVIE_DIR}/.{Path(VIDEO).name}{PARTIAL_SUFFIX}"

    def crash_mid_copy(source: Path, target: Path) -> None:
        if target.name.endswith(f".mkv{PARTIAL_SUFFIX}"):
            put(target, b"half a file")
            raise RuntimeError("power cut")
        real_copy(source, target)

    monkeypatch.setattr(os, "rename", _cross_device)
    monkeypatch.setattr(organizer, "_copy", crash_mid_copy)
    with pytest.raises(RuntimeError):
        await run()
    assert tree(completed) == {partial: b"half a file", SUB: SUB_TEXT}

    monkeypatch.setattr(organizer, "_copy", real_copy)
    await run()

    assert tree(completed) == {SUB: SUB_TEXT, VIDEO: content}
    assert list(tree(job_dir)) == [MARKER]


async def test_stale_partial_is_deleted(run: Run, content: bytes, completed: Path) -> None:
    put(completed / MOVIE_DIR / f".{Path(VIDEO).name}{PARTIAL_SUFFIX}", b"half a file")

    await run()

    assert tree(completed) == {SUB: SUB_TEXT, VIDEO: content}


async def test_same_size_destination_counts_as_moved(
    run: Run, video: Path, content: bytes, job_dir: Path, completed: Path
) -> None:
    await run()
    # A crash after the rename but before the source was deleted leaves both copies.
    put(video, content)

    await run()

    assert tree(completed) == {SUB: SUB_TEXT, VIDEO: content}
    assert list(tree(job_dir)) == [MARKER]


async def test_guard_rejects_symlink_escape(
    run: Run, content: bytes, job_dir: Path, tmp_path: Path, completed: Path
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (completed / "movies").mkdir()
    (completed / MOVIE_DIR).symlink_to(outside, target_is_directory=True)

    with pytest.raises(PathEscapeError):
        await run()

    assert tree(outside) == {}
    assert tree(job_dir) == {"video.en.srt": SUB_TEXT, "video.mkv": content}


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        (Movie("../../../outside", None), "movies/outside/outside WEBDL-1080p.mkv"),
        (Movie("/etc/passwd", 2008), "movies/etcpasswd (2008)/etcpasswd (2008) WEBDL-1080p.mkv"),
        (
            Episode("../../x", 1, 1, "/tmp/y"),
            "tv-shows/x/Season 1/x - S01E01 - tmpy WEBDL-1080p.mkv",
        ),
        (Other("../../outside/evil", "../id"), "other/outsideevil [id].mkv"),
    ],
)
async def test_hostile_titles_stay_inside_completed_dir(
    make_job: Callable[..., Path], completed: Path, target: Target, expected: str
) -> None:
    video = make_job("job-hostile")

    result = await _organize(video, completed, target)

    assert result.video == completed / expected
    assert list(tree(completed)) == [expected]


async def test_title_with_nothing_left_raises(
    make_job: Callable[..., Path], completed: Path
) -> None:
    video = make_job("job-empty")

    with pytest.raises(OrganizeError):
        await _organize(video, completed, Episode("../../..", 1, 1, "x"))

    assert tree(completed) == {}


@pytest.fixture
def big_video(job_dir: Path) -> Path:
    chunk = os.urandom(1024 * 1024)
    path = job_dir / "big.mkv"
    with path.open("wb") as writer:
        for _ in range(128):
            writer.write(chunk)
    return path


async def test_copy_fallback_runs_off_the_loop(
    big_video: Path, completed: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_probe(path: Path) -> ProbeResult:
        return ProbeResult(1920, 1080, "h264", "aac", 60.0, True)

    threads: list[int] = []
    real_copy = organizer._copy

    def recording_copy(source: Path, partial: Path) -> None:
        threads.append(threading.get_ident())
        real_copy(source, partial)

    monkeypatch.setattr(organizer, "probe", fake_probe)
    monkeypatch.setattr(organizer, "_copy", recording_copy)
    monkeypatch.setattr(os, "rename", _cross_device)

    # The loop guard fails this test if the 128 MiB copy blocks the event loop.
    result = await _organize(big_video, completed)

    assert result.size == 128 * 1024 * 1024
    assert threads and threading.get_ident() not in threads


@pytest.mark.parametrize("fixture", ["audio", "garbage"])
async def test_rejects_file_without_video_stream(
    make_job: Callable[..., Path], completed: Path, fixture: str
) -> None:
    video = make_job("job-bad", fixture)

    with pytest.raises(InvalidMediaError):
        await _organize(video, completed)

    assert tree(completed) == {}
    assert list(tree(video.parent)) == [video.name]


async def test_is_organized(run: Run, video: Path, content: bytes, job_dir: Path) -> None:
    assert not is_organized(job_dir, video)

    result = await run()

    assert is_organized(job_dir, video)
    # Once the pipeline deletes the job dir it passes the recorded completed_path.
    gone = job_dir.parent / "deleted-job"
    assert not is_organized(gone, gone / video.name)
    assert is_organized(gone, gone / video.name, result.video)
    # Still in the job dir → not organised, whatever was recorded.
    put(video, content)
    assert not is_organized(job_dir, video, result.video)
