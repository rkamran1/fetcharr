"""requests, jobs and job_logs

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "requests",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("media_type", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("numbering", sa.String(), nullable=True),
        sa.Column("radarr_movie_id", sa.Integer(), nullable=True),
        sa.Column("sonarr_series_id", sa.Integer(), nullable=True),
        sa.Column("options", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("requests", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_requests_created_at"), ["created_at"], unique=False)

    op.create_table(
        "jobs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("request_id", sa.String(), nullable=False),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("extractor", sa.String(), nullable=True),
        sa.Column("video_id", sa.String(), nullable=True),
        sa.Column("stream_type", sa.String(), nullable=True),
        sa.Column("source_title", sa.String(), nullable=True),
        sa.Column("thumbnail_url", sa.String(), nullable=True),
        sa.Column("duration", sa.Float(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("phase", sa.String(), nullable=True),
        sa.Column("last_completed_step", sa.String(), nullable=True),
        sa.Column("step_timings", sa.JSON(), nullable=False),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("progress_pct", sa.Float(), nullable=True),
        sa.Column("downloaded_bytes", sa.Integer(), nullable=True),
        sa.Column("total_bytes", sa.Integer(), nullable=True),
        sa.Column("speed_bps", sa.Float(), nullable=True),
        sa.Column("eta_s", sa.Integer(), nullable=True),
        sa.Column("job_dir", sa.String(), nullable=False),
        sa.Column("completed_path", sa.String(), nullable=True),
        sa.Column("sidecar_paths", sa.JSON(), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column("probed", sa.JSON(), nullable=True),
        sa.Column("import_status", sa.String(), nullable=False),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["request_id"], ["requests.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.create_index("ix_jobs_created_at", ["created_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_jobs_request_id"), ["request_id"], unique=False)
        batch_op.create_index("ix_jobs_status", ["status"], unique=False)
        batch_op.create_index("ix_jobs_video_id", ["video_id"], unique=False)

    op.create_table(
        "job_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("ts", sa.DateTime(), nullable=False),
        sa.Column("level", sa.String(), nullable=False),
        sa.Column("line", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("job_logs", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_job_logs_job_id"), ["job_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("job_logs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_job_logs_job_id"))

    op.drop_table("job_logs")
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.drop_index("ix_jobs_video_id")
        batch_op.drop_index("ix_jobs_status")
        batch_op.drop_index(batch_op.f("ix_jobs_request_id"))
        batch_op.drop_index("ix_jobs_created_at")

    op.drop_table("jobs")
    with op.batch_alter_table("requests", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_requests_created_at"))

    op.drop_table("requests")
