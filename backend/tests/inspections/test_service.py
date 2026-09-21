from collections.abc import AsyncIterator
from datetime import timedelta

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select, update

from app.db.base import utcnow
from app.db.session import Database
from app.inspections.exceptions import InspectError
from app.inspections.models import Inspection
from app.inspections.service import InspectionService
from app.sites.service import SitesService
from app.ytdlp import inspect
from tests.fake_ytdlp import FakeYtdlp

URL = "https://www.youtube.com/watch?v=aqz-KE-bpKQ"


@pytest.fixture
async def db(migrated_db_url: str) -> AsyncIterator[Database]:
    database = Database(migrated_db_url)
    yield database
    await database.dispose()


def _service(db: Database) -> InspectionService:
    return InspectionService(db, SitesService(db, Fernet.generate_key()))


async def _rows(db: Database) -> list[Inspection]:
    async with db.read_session() as session:
        return list(await session.scalars(select(Inspection).order_by(Inspection.id)))


async def test_miss_runs_ytdlp_and_stores(db: Database, fake_ytdlp: FakeYtdlp) -> None:
    result = await _service(db).inspect(URL)

    assert len(fake_ytdlp.calls) == 1
    assert result.stream_type == "dash"
    [row] = await _rows(db)
    assert (row.id, row.url) == (result.inspection_id, URL)
    assert row.expires_at - row.created_at == timedelta(minutes=30)
    assert row.info["title"] == result.title


async def test_hit_reuses_cached_row(db: Database, fake_ytdlp: FakeYtdlp) -> None:
    service = _service(db)
    first = await service.inspect(URL)

    second = await service.inspect(URL)

    assert second == first
    assert len(fake_ytdlp.calls) == 1


async def test_expired_row_runs_again_and_is_purged(db: Database, fake_ytdlp: FakeYtdlp) -> None:
    service = _service(db)
    first = await service.inspect(URL)
    async with db.write_session() as session:
        await session.execute(update(Inspection).values(expires_at=utcnow() - timedelta(seconds=1)))

    second = await service.inspect(URL)

    assert len(fake_ytdlp.calls) == 2
    assert second.inspection_id != first.inspection_id
    assert [r.id for r in await _rows(db)] == [second.inspection_id]


@pytest.mark.parametrize(
    ("fixture", "status", "needs_cookies"),
    [
        ("age.txt", 422, True),
        ("unsupported.txt", 422, False),
        ("unavailable.txt", 422, False),
        ("network.txt", 502, False),
        (None, 504, False),
    ],
)
async def test_ytdlp_errors_map_to_inspect_errors(
    db: Database,
    fake_ytdlp: FakeYtdlp,
    monkeypatch: pytest.MonkeyPatch,
    fixture: str | None,
    status: int,
    needs_cookies: bool,
) -> None:
    if fixture is None:
        monkeypatch.setattr(inspect, "INSPECT_TIMEOUT_S", 1.0)
        fake_ytdlp.hangs()
    else:
        fake_ytdlp.fails_with(fixture)

    with pytest.raises(InspectError) as caught:
        await _service(db).inspect(URL)

    assert (caught.value.status, caught.value.needs_cookies) == (status, needs_cookies)
    assert await _rows(db) == []
