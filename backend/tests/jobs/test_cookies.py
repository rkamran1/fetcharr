"""A download with its site's cookies: 0600 file, cleanup, skip, write-back, flagging (§8)."""

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from app.config import Settings
from app.db.session import Database
from app.jobs.constants import JobStatus
from app.jobs.manager import JobManager
from app.settings.utils import decrypt
from app.sites.models import SiteCookies
from app.sites.service import SitesService
from tests.conftest import CANARY, cookie_file, cookie_line, exists, wait_until
from tests.fake_ytdlp import FakeYtdlp
from tests.jobs.conftest import job_dir_of, wait_for_status

YOUTUBE_URL = "https://www.youtube.com/watch?v=aqz-KE-bpKQ"
STORED = cookie_file(cookie_line(".youtube.com"), cookie_line(".google.com", "NID"))
REFRESHED = cookie_file(cookie_line(".youtube.com", "SID", "refreshed-value"))
SIGN_IN = "ERROR: [youtube] aqz-KE-bpKQ: Sign in to confirm you're not a bot"
FORBIDDEN = "ERROR: unable to download video data: HTTP Error 403: Forbidden"


@pytest.fixture
def video(media: dict[str, Path]) -> Path:
    """Real media: the organize step probes the downloaded file."""
    return media["small"]


@pytest.fixture
def sites(db: Database, secret_key: bytes) -> SitesService:
    return SitesService(db, secret_key)


@pytest.fixture
async def with_cookies(sites: SitesService) -> SitesService:
    await sites.upload("youtube", STORED)
    return sites


async def _row(db: Database) -> SiteCookies:
    async with db.read_session() as session:
        row = await session.get(SiteCookies, "youtube")
    assert row is not None
    return row


async def _run(
    manager: JobManager,
    new_job: Callable[..., Any],
    read_job: Callable[[str], Any],
    **fields: Any,
) -> tuple[str, Any]:
    job_id = await new_job(**{"url": YOUTUBE_URL, "site_key": "youtube", **fields})
    manager.wake()
    return job_id, await wait_for_status(read_job, job_id, JobStatus.COMPLETED, JobStatus.FAILED)


def _cookies_arg(argv: list[str]) -> str | None:
    return argv[argv.index("--cookies") + 1] if "--cookies" in argv else None


# ------------------------------------------------------------------- AC5


async def test_download_uses_site_cookies(
    manager: JobManager,
    with_cookies: SitesService,
    new_job: Callable[..., Any],
    read_job: Callable[[str], Any],
    fake_ytdlp: FakeYtdlp,
    video: Path,
    settings: Settings,
) -> None:
    fake_ytdlp.downloads(video)

    job_id, job = await _run(manager, new_job, read_job)

    assert job.status == JobStatus.COMPLETED, job.error_message
    [seen] = fake_ytdlp.cookies_seen
    assert seen["path"] == str(job_dir_of(settings, job_id) / "cookies.txt")
    assert seen["mode"] == 0o600
    assert seen["text"] == STORED
    assert _cookies_arg(fake_ytdlp.calls[0]) == seen["path"]
    assert not exists(Path(seen["path"]))


async def test_download_deletes_cookies_after_failure(
    manager: JobManager,
    with_cookies: SitesService,
    new_job: Callable[..., Any],
    read_job: Callable[[str], Any],
    fake_ytdlp: FakeYtdlp,
) -> None:
    fake_ytdlp.downloads(exit_code=1, stderr="ERROR: something broke")

    _job_id, job = await _run(manager, new_job, read_job)

    assert job.status == JobStatus.FAILED
    [seen] = fake_ytdlp.cookies_seen
    assert seen["mode"] == 0o600
    assert not exists(Path(seen["path"]))


async def test_download_deletes_cookies_after_cancel(
    manager: JobManager,
    with_cookies: SitesService,
    new_job: Callable[..., Any],
    read_job: Callable[[str], Any],
    fake_ytdlp: FakeYtdlp,
    tmp_path: Path,
) -> None:
    fake_ytdlp.downloads(gate=tmp_path / "never")
    job_id = await new_job(url=YOUTUBE_URL, site_key="youtube")
    manager.wake()
    await wait_until(lambda: bool(fake_ytdlp.cookies_seen))

    assert manager.request_cancel(job_id)
    job = await wait_for_status(read_job, job_id, JobStatus.CANCELLED)

    assert job.status == JobStatus.CANCELLED
    [seen] = fake_ytdlp.cookies_seen
    assert seen["mode"] == 0o600
    assert not exists(Path(seen["path"]))


# ------------------------------------------------------------------- AC6


async def test_skip_cookies_runs_without_cookies(
    manager: JobManager,
    with_cookies: SitesService,
    new_job: Callable[..., Any],
    read_job: Callable[[str], Any],
    fake_ytdlp: FakeYtdlp,
    video: Path,
) -> None:
    fake_ytdlp.downloads(video)

    _job_id, job = await _run(manager, new_job, read_job, use_cookies=False)

    assert job.status == JobStatus.COMPLETED, job.error_message
    assert _cookies_arg(fake_ytdlp.calls[0]) is None
    assert fake_ytdlp.cookies_seen == []


async def test_unmatched_host_gets_no_cookies(
    manager: JobManager,
    with_cookies: SitesService,
    new_job: Callable[..., Any],
    read_job: Callable[[str], Any],
    fake_ytdlp: FakeYtdlp,
    video: Path,
) -> None:
    fake_ytdlp.downloads(video)

    _job_id, job = await _run(
        manager, new_job, read_job, url="https://example.com/v", site_key=None
    )

    assert job.status == JobStatus.COMPLETED, job.error_message
    assert _cookies_arg(fake_ytdlp.calls[0]) is None


# ------------------------------------------------------------------- AC7


async def test_write_back_after_success(
    manager: JobManager,
    with_cookies: SitesService,
    db: Database,
    secret_key: bytes,
    new_job: Callable[..., Any],
    read_job: Callable[[str], Any],
    fake_ytdlp: FakeYtdlp,
    video: Path,
) -> None:
    fake_ytdlp.downloads(video)
    fake_ytdlp.rewrites_cookies(REFRESHED)

    _job_id, job = await _run(manager, new_job, read_job)

    assert job.status == JobStatus.COMPLETED, job.error_message
    row = await _row(db)
    assert decrypt(row.enc_blob, secret_key) == REFRESHED
    assert row.cookie_count == 1
    assert row.last_used_at is not None


async def test_unchanged_file_only_records_use(
    manager: JobManager,
    with_cookies: SitesService,
    db: Database,
    new_job: Callable[..., Any],
    read_job: Callable[[str], Any],
    fake_ytdlp: FakeYtdlp,
    video: Path,
) -> None:
    before = await _row(db)
    fake_ytdlp.downloads(video)

    await _run(manager, new_job, read_job)

    row = await _row(db)
    assert row.enc_blob == before.enc_blob
    assert row.last_used_at is not None


async def test_no_write_back_after_failure(
    manager: JobManager,
    with_cookies: SitesService,
    db: Database,
    new_job: Callable[..., Any],
    read_job: Callable[[str], Any],
    fake_ytdlp: FakeYtdlp,
) -> None:
    before = await _row(db)
    fake_ytdlp.downloads(exit_code=1, stderr="ERROR: something broke")
    fake_ytdlp.rewrites_cookies(REFRESHED)

    _job_id, job = await _run(manager, new_job, read_job)

    assert job.status == JobStatus.FAILED
    row = await _row(db)
    assert row.enc_blob == before.enc_blob
    assert row.last_used_at is None


# ------------------------------------------------------------------- AC8


@pytest.mark.parametrize("stderr", [SIGN_IN, FORBIDDEN])
async def test_auth_failure_flags_site(
    manager: JobManager,
    with_cookies: SitesService,
    db: Database,
    new_job: Callable[..., Any],
    read_job: Callable[[str], Any],
    fake_ytdlp: FakeYtdlp,
    stderr: str,
) -> None:
    fake_ytdlp.downloads(exit_code=1, stderr=stderr)

    _job_id, job = await _run(manager, new_job, read_job)

    assert job.status == JobStatus.FAILED
    assert (await _row(db)).flagged_invalid is True

    await with_cookies.upload("youtube", STORED)
    assert (await _row(db)).flagged_invalid is False


async def test_auth_failure_without_cookies_does_not_flag(
    manager: JobManager,
    with_cookies: SitesService,
    db: Database,
    new_job: Callable[..., Any],
    read_job: Callable[[str], Any],
    fake_ytdlp: FakeYtdlp,
) -> None:
    fake_ytdlp.downloads(exit_code=1, stderr=SIGN_IN)

    _job_id, job = await _run(manager, new_job, read_job, use_cookies=False)

    assert job.status == JobStatus.FAILED
    assert (await _row(db)).flagged_invalid is False


async def test_other_failures_do_not_flag(
    manager: JobManager,
    with_cookies: SitesService,
    db: Database,
    new_job: Callable[..., Any],
    read_job: Callable[[str], Any],
    fake_ytdlp: FakeYtdlp,
) -> None:
    fake_ytdlp.downloads(exit_code=1, stderr="ERROR: [youtube] x: Video unavailable")

    await _run(manager, new_job, read_job)

    assert (await _row(db)).flagged_invalid is False


# ------------------------------------------------------------------ AC10


@pytest.mark.parametrize("exit_code", [0, 1])
async def test_no_cookie_values_in_logs(
    manager: JobManager,
    with_cookies: SitesService,
    new_job: Callable[..., Any],
    read_job: Callable[[str], Any],
    read_logs: Callable[[str], Any],
    fake_ytdlp: FakeYtdlp,
    caplog: pytest.LogCaptureFixture,
    exit_code: int,
) -> None:
    caplog.set_level(logging.DEBUG)
    fake_ytdlp.downloads(
        video,
        exit_code=exit_code,
        stderr=f"[debug] Cookie: SID={CANARY}\nERROR: request failed; Set-Cookie: SID={CANARY}",
    )

    job_id, job = await _run(manager, new_job, read_job)

    logs = await read_logs(job_id)
    assert any("[redacted]" in line for line in logs)
    assert not any(CANARY in line for line in logs)
    assert CANARY not in (job.error_message or "")
    assert CANARY not in caplog.text
