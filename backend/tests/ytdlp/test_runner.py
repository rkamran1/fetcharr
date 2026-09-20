import asyncio
import os
from pathlib import Path

import pytest
from tenacity import AsyncRetrying, RetryCallState, wait_none

from app.ytdlp.command import build_argv
from app.ytdlp.runner import (
    DOWNLOAD_WAIT,
    DownloadCancelled,
    Progress,
    YtDlpFailed,
    YtDlpFatal,
    cleanup_partials,
    download,
    is_postprocessing,
    parse_progress,
    read_final_path,
    run_once,
)
from app.ytdlp.schemas import DownloadOptions
from app.ytdlp.stream import Resolved
from tests.conftest import wait_until
from tests.fake_ytdlp import FakeYtdlp

URL = "https://example.com/watch?v=x"


def argv_for(job_dir: Path, fragments: int = 4) -> list[str]:
    return build_argv(
        URL,
        DownloadOptions(quality="best"),
        Resolved(stream_type="http", fragments=fragments, use_aria2c=False),
        job_dir=job_dir,
        js_runtime=None,
    )


@pytest.fixture
def job_dir(tmp_path: Path) -> Path:
    path = tmp_path / "incomplete" / "job-1"
    path.mkdir(parents=True)
    return path


class Collector:
    def __init__(self) -> None:
        self.progress: list[Progress] = []
        self.logs: list[str] = []
        self.attempts: list[int] = []


def collector() -> Collector:
    return Collector()


async def run_download(
    job_dir: Path, sink: Collector, *, retries: int = 0, fragments: int = 4
) -> Path:
    return await download(
        argv_for(job_dir, fragments),
        job_dir=job_dir,
        retries=retries,
        cancel=asyncio.Event(),
        on_progress=sink.progress.append,
        on_log=sink.logs.append,
        on_attempt=sink.attempts.append,
        wait=wait_none(),
    )


def test_parse_progress_reads_the_fields() -> None:
    line = (
        'FA_PROGRESS {"status": "downloading", "downloaded_bytes": 500, '
        '"total_bytes": 2000, "speed": 1024.5, "eta": 12}'
    )

    progress = parse_progress(line)

    assert progress == Progress(
        status="downloading",
        downloaded_bytes=500,
        total_bytes=2000,
        speed_bps=1024.5,
        eta_s=12,
        pct=25.0,
    )


def test_parse_progress_tolerates_unknown_values() -> None:
    line = (
        'FA_PROGRESS {"status": "downloading", "downloaded_bytes": 10, "total_bytes": null, '
        '"total_bytes_estimate": 100, "speed": null, "eta": null}'
    )

    progress = parse_progress(line)

    assert progress is not None
    assert (progress.total_bytes, progress.speed_bps, progress.eta_s, progress.pct) == (
        100,
        None,
        None,
        10.0,
    )
    assert parse_progress("[download] 10% of 1MiB") is None
    assert parse_progress("FA_PROGRESS not json") is None


def test_postprocessing_lines_are_recognised() -> None:
    assert is_postprocessing('[Merger] Merging formats into "video.mkv"')
    assert is_postprocessing("[VideoRemuxer] Remuxing video from mp4 to mkv")
    assert not is_postprocessing("[download] Destination: video.f137.mp4")


def test_read_final_path_takes_the_last_line(job_dir: Path) -> None:
    (job_dir / "final_path").write_text(f"{job_dir}/video.f137.mp4\n{job_dir}/video.mkv\n")

    assert read_final_path(job_dir) == job_dir / "video.mkv"


def test_cleanup_removes_partials_only_inside_the_job_dir(job_dir: Path) -> None:
    sibling = job_dir.parent / "job-2"
    sibling.mkdir()
    for root in (job_dir, sibling):
        for name in ("video.mkv", "video.part", "video.ytdl", "video-Frag0.part", "video.temp.mkv"):
            (root / name).write_text("x")
    (job_dir / "tmp").mkdir()
    (job_dir / "tmp" / "nested.part").write_text("x")

    cleanup_partials(job_dir)

    assert sorted(p.name for p in job_dir.rglob("*") if p.is_file()) == ["video.mkv"]
    assert len([p for p in sibling.iterdir() if p.is_file()]) == 5


async def test_downloads_and_reports_progress(job_dir: Path, fake_ytdlp: FakeYtdlp) -> None:
    fake_ytdlp.downloads(progress_lines=4)
    sink = collector()

    final = await run_download(job_dir, sink)

    assert final == job_dir / "video.mkv"
    assert final.is_file()
    assert [p.downloaded_bytes for p in sink.progress if not p.postprocessing] == [
        2_500_000,
        5_000_000,
        7_500_000,
        10_000_000,
    ]
    assert sink.progress[-1].postprocessing is True
    assert sink.attempts == [1]


async def test_failing_download_runs_retries_plus_one_attempts(
    job_dir: Path, fake_ytdlp: FakeYtdlp
) -> None:
    fake_ytdlp.downloads(exit_code=1, stderr="ERROR: unable to download video data")
    sink = collector()

    with pytest.raises(YtDlpFailed) as error:
        await run_download(job_dir, sink, retries=2)

    assert error.value.exit_code == 1
    assert len(fake_ytdlp.calls) == 3
    assert sink.attempts == [1, 2, 3]


def test_wait_schedule_matches_the_script() -> None:
    def wait_before(attempt: int) -> float:
        state = RetryCallState(AsyncRetrying(), fn=None, args=(), kwargs={})
        state.attempt_number = attempt
        return DOWNLOAD_WAIT(state)

    assert [wait_before(n) for n in (1, 2, 3, 4)] == [4, 6, 8, 10]


async def test_exit_code_2_downgrades_fragments_on_the_next_attempt(
    job_dir: Path, fake_ytdlp: FakeYtdlp
) -> None:
    fake_ytdlp.downloads(exit_code=2, stderr="ERROR: unable to download video data: HTTP Error 500")
    sink = collector()

    with pytest.raises(YtDlpFailed):
        await run_download(job_dir, sink, retries=1)

    first, second = fake_ytdlp.calls
    assert first[first.index("--concurrent-fragments") + 1] == "4"
    assert second[second.index("--concurrent-fragments") + 1] == "1"
    assert any("--concurrent-fragments 1" in line for line in sink.logs)


async def test_fatal_errors_are_not_retried(job_dir: Path, fake_ytdlp: FakeYtdlp) -> None:
    fake_ytdlp.downloads(exit_code=1, stderr="ERROR: Unsupported URL: https://example.com/x")
    sink = collector()

    with pytest.raises(YtDlpFatal) as error:
        await run_download(job_dir, sink, retries=3)

    assert error.value.kind == "unsupported"
    assert len(fake_ytdlp.calls) == 1


async def test_every_attempt_is_logged(job_dir: Path, fake_ytdlp: FakeYtdlp) -> None:
    fake_ytdlp.downloads(exit_code=1, stderr="ERROR: unable to download video data")
    sink = collector()

    with pytest.raises(YtDlpFailed):
        await run_download(job_dir, sink, retries=2)

    assert [line for line in sink.logs if line.startswith("yt-dlp attempt")] == [
        "yt-dlp attempt 1",
        "yt-dlp attempt 2",
        "yt-dlp attempt 3",
    ]
    # before_sleep fires between attempts, so twice for three attempts.
    assert len([line for line in sink.logs if "retrying in" in line]) == 2


async def test_cancel_terminates_the_process_group(job_dir: Path, fake_ytdlp: FakeYtdlp) -> None:
    fake_ytdlp.downloads(progress_lines=1, spawn_child=True)
    sink = collector()
    cancel = asyncio.Event()

    task = asyncio.create_task(
        run_once(
            argv_for(job_dir),
            job_dir=job_dir,
            cancel=cancel,
            on_progress=sink.progress.append,
            on_log=sink.logs.append,
        )
    )
    await wait_until(fake_ytdlp.pids_file.exists)
    pids = fake_ytdlp.pids()
    cancel.set()

    with pytest.raises(DownloadCancelled):
        await task

    for pid in pids:
        await wait_until(lambda pid=pid: _gone(pid), seconds=5)


def _gone(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return False
