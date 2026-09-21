"""history search (FTS5 over request, source and episode titles) and jobs.file_deleted_at

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-21

The search index is SQLite-only (§3.1): on Postgres the ILIKE fallback in
`app.requests.service` answers the same queries without it.

**A batch-mode rebuild of `jobs` drops these triggers** (SQLite drops a table's triggers
with it). A later revision that uses `batch_alter_table("jobs")` must re-run `TRIGGERS`.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Keyed by job_id, not rowid: `jobs` has a string primary key, so its implicit rowids
# may be renumbered by VACUUM or a batch-mode rebuild.
CREATE_INDEX = """
CREATE VIRTUAL TABLE jobs_fts USING fts5(
    job_id UNINDEXED,
    request_id UNINDEXED,
    request_title,
    source_title,
    episode_title,
    tokenize = 'unicode61 remove_diacritics 2'
)
"""

_INSERT_NEW = """
    INSERT INTO jobs_fts (job_id, request_id, request_title, source_title, episode_title)
    VALUES (
        new.id,
        new.request_id,
        (SELECT title FROM requests WHERE id = new.request_id),
        new.source_title,
        new.episode_title
    );
"""

TRIGGERS = (
    f"""
    CREATE TRIGGER jobs_fts_insert AFTER INSERT ON jobs BEGIN
    {_INSERT_NEW}
    END
    """,
    f"""
    CREATE TRIGGER jobs_fts_update AFTER UPDATE OF request_id, source_title, episode_title
    ON jobs BEGIN
        DELETE FROM jobs_fts WHERE job_id = old.id;
    {_INSERT_NEW}
    END
    """,
    # Also fired by the ON DELETE CASCADE from `requests`.
    """
    CREATE TRIGGER jobs_fts_delete AFTER DELETE ON jobs BEGIN
        DELETE FROM jobs_fts WHERE job_id = old.id;
    END
    """,
    """
    CREATE TRIGGER requests_fts_title AFTER UPDATE OF title ON requests BEGIN
        UPDATE jobs_fts SET request_title = new.title WHERE request_id = new.id;
    END
    """,
)

BACKFILL = """
INSERT INTO jobs_fts (job_id, request_id, request_title, source_title, episode_title)
SELECT jobs.id, jobs.request_id, requests.title, jobs.source_title, jobs.episode_title
FROM jobs JOIN requests ON requests.id = jobs.request_id
"""

TRIGGER_NAMES = ("jobs_fts_insert", "jobs_fts_update", "jobs_fts_delete", "requests_fts_title")


def upgrade() -> None:
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("file_deleted_at", sa.DateTime(), nullable=True))
    # After the batch rebuild above, so the triggers are created on the final table.
    if op.get_bind().dialect.name == "sqlite":
        op.execute(CREATE_INDEX)
        for trigger in TRIGGERS:
            op.execute(trigger)
        op.execute(BACKFILL)


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        for name in TRIGGER_NAMES:
            op.execute(f"DROP TRIGGER IF EXISTS {name}")
        op.execute("DROP TABLE IF EXISTS jobs_fts")
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.drop_column("file_deleted_at")
