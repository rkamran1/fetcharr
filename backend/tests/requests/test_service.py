"""History search (FTS5 and its ILIKE fallback) and the history query plan (§10, AC3/AC4/AC8)."""

import re
import uuid
from collections.abc import AsyncIterator
from datetime import date
from typing import Any

import pytest
from sqlalchemy import Select, delete, text, update
from sqlalchemy.dialects import sqlite

from app.db.base import utcnow
from app.db.session import Database
from app.jobs.constants import ImportStatus, JobStatus
from app.jobs.models import Job
from app.requests.models import Request
from app.requests.schemas import RequestFilters
from app.requests.service import (
    fts_request_ids,
    history_queries,
    ilike_request_ids,
    jobs_of,
)


@pytest.fixture
async def db(migrated_db_url: str) -> AsyncIterator[Database]:
    database = Database(migrated_db_url)
    yield database
    await database.dispose()


async def add(
    db: Database,
    title: str,
    *jobs: dict[str, Any],
    media_type: str = "other",
) -> str:
    """One request and its jobs; each job dict may set `source_title`/`episode_title`."""
    request_id = str(uuid.uuid4())
    async with db.write_session() as session:
        session.add(
            Request(
                id=request_id,
                media_type=media_type,
                title=title,
                options={},
                created_at=utcnow(),
            )
        )
        await session.flush()
        for fields in jobs or ({"source_title": title},):
            session.add(
                Job(
                    id=fields.pop("id", str(uuid.uuid4())),
                    request_id=request_id,
                    url="https://example.com/v",
                    status=JobStatus.COMPLETED,
                    step_timings={},
                    sidecar_paths=[],
                    job_dir="/tmp/unused",
                    created_at=utcnow(),
                    **fields,
                )
            )
    return request_id


async def found(db: Database, query: Select[tuple[str]] | None) -> set[str]:
    assert query is not None
    async with db.read_session() as session:
        return set(await session.scalars(query))


@pytest.fixture
async def library(db: Database) -> dict[str, str]:
    return {
        "bunny": await add(db, "Big Buck Bunny", {"source_title": "Big Buck Bunny 60fps 4K"}),
        "sintel": await add(
            db, "Sintel", {"source_title": "Sintel - Open Movie by Blender"}, media_type="movie"
        ),
        "show": await add(
            db,
            "Some Show",
            {"source_title": "Some Show S01E01 upload", "episode_title": "Pilot"},
            {"source_title": "Some Show S01E02 upload", "episode_title": "The Return"},
            media_type="tv",
        ),
        "tears": await add(db, "Tears of Steel", {"source_title": "Mango trailer"}),
    }


# ------------------------------------------------------------------------ AC3: FTS5


@pytest.mark.parametrize(
    ("q", "key"),
    [("Tears", "tears"), ("mango", "tears"), ("pilot", "show"), ("return", "show")],
    ids=["request title", "source title", "episode title", "second episode title"],
)
async def test_fts_finds_by_each_title(
    db: Database, library: dict[str, str], q: str, key: str
) -> None:
    assert await found(db, fts_request_ids(q)) == {library[key]}


async def test_fts_prefix_match_from_a_partial_word(db: Database, library: dict[str, str]) -> None:
    assert await found(db, fts_request_ids("bunn")) == {library["bunny"]}
    assert await found(db, fts_request_ids("big bu")) == {library["bunny"]}
    assert await found(db, fts_request_ids("SIN")) == {library["sintel"]}
    # Every word has to match the same job.
    assert await found(db, fts_request_ids("bunny sintel")) == set()


async def test_fts_ignores_accents(db: Database) -> None:
    request_id = await add(db, "Amélie")

    assert await found(db, fts_request_ids("amelie")) == {request_id}


async def test_fts_follows_job_insert_update_and_delete(db: Database) -> None:
    job_id = str(uuid.uuid4())
    request_id = await add(db, "Elephants Dream", {"id": job_id, "source_title": "Orange"})
    assert await found(db, fts_request_ids("orange")) == {request_id}

    async with db.write_session() as session:
        await session.execute(
            update(Job).where(Job.id == job_id).values(source_title="Proog", episode_title="Emo")
        )
    assert await found(db, fts_request_ids("orange")) == set()
    assert await found(db, fts_request_ids("proog")) == {request_id}
    assert await found(db, fts_request_ids("emo")) == {request_id}

    async with db.write_session() as session:
        await session.execute(delete(Job).where(Job.id == job_id))
    assert await found(db, fts_request_ids("proog")) == set()
    assert await found(db, fts_request_ids("elephants")) == set()


async def test_fts_follows_a_request_title_change_and_its_cascade(db: Database) -> None:
    request_id = await add(db, "Cosmos Laundromat", {"source_title": "First Cycle"})

    async with db.write_session() as session:
        await session.execute(
            update(Request).where(Request.id == request_id).values(title="Glass Half")
        )
    assert await found(db, fts_request_ids("cosmos")) == set()
    assert await found(db, fts_request_ids("glass")) == {request_id}

    # Deleting the request cascades to its jobs, whose delete trigger clears the index.
    async with db.write_session() as session:
        await session.execute(delete(Request).where(Request.id == request_id))
    assert await found(db, fts_request_ids("cycle")) == set()
    async with db.read_session() as session:
        assert await session.scalar(text("SELECT count(*) FROM jobs_fts")) == 0


# ---------------------------------------------------------------- AC4: ILIKE fallback


@pytest.mark.parametrize(
    "q", ["bunn", "big buck", "pilot", "sintel", "nothing-here", "SOME s01e02"]
)
async def test_ilike_fallback_matches_fts(db: Database, library: dict[str, str], q: str) -> None:
    assert await found(db, ilike_request_ids(q)) == await found(db, fts_request_ids(q))


# ------------------------------------------------------------------ AC8: query plan


def _sql(query: Select[Any]) -> str:
    return str(query.compile(dialect=sqlite.dialect(), compile_kwargs={"literal_binds": True}))


async def _plan(db: Database, query: Select[Any]) -> list[str]:
    async with db.read_session() as session:
        rows = await session.execute(text(f"EXPLAIN QUERY PLAN {_sql(query)}"))
        return [row[-1] for row in rows]


def _full_scans(plan: list[str]) -> list[str]:
    """A plain `SCAN requests` or `SCAN jobs` (no index) reads the whole table."""
    return [line for line in plan if FULL_SCAN.match(line)]


FULL_SCAN = re.compile(r"^SCAN (requests|jobs)\b(?!.* USING )")


@pytest.mark.parametrize(
    "filters",
    [
        RequestFilters(q="bunn", type="tv"),
        RequestFilters(q="bunn", status=JobStatus.COMPLETED, site="youtube"),
        RequestFilters(status=JobStatus.FAILED, import_status=ImportStatus.NOT_IMPORTED),
        RequestFilters(type="movie", from_=date(2026, 1, 1), to=date(2026, 12, 31)),
        RequestFilters(),
    ],
    ids=["search+type", "search+job filters", "job filters", "type+dates", "no filters"],
)
async def test_history_query_plan_uses_indexes(
    db: Database, library: dict[str, str], filters: RequestFilters
) -> None:
    count, page = history_queries(filters, "sqlite")

    for query in (count, page):
        plan = await _plan(db, query)
        assert _full_scans(plan) == [], plan
        # Every plan reaches `requests` through one of its indexes.
        assert any(line.split()[1] == "requests" and " INDEX " in line for line in plan), plan
        if filters.q:
            assert any("jobs_fts VIRTUAL TABLE INDEX" in line for line in plan), plan
        if filters.status:
            assert any("SEARCH jobs USING INDEX ix_jobs_status" in line for line in plan), plan

    jobs_plan = await _plan(db, jobs_of(list(library.values())))
    assert "SEARCH jobs USING INDEX ix_jobs_request_id (request_id=?)" in jobs_plan
    assert _full_scans(jobs_plan) == []


def test_full_scan_detection() -> None:
    assert _full_scans(
        ["SCAN requests", "SCAN jobs", "SCAN jobs_fts VIRTUAL TABLE INDEX 0:M5"]
    ) == [
        "SCAN requests",
        "SCAN jobs",
    ]
    assert _full_scans(["SCAN requests USING INDEX ix_requests_created_at"]) == []
