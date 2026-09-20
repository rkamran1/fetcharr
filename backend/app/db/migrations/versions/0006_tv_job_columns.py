"""which episode a job is downloading (tv)

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("season", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("episode", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("sonarr_episode_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("episode_title", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("air_date", sa.Date(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.drop_column("air_date")
        batch_op.drop_column("episode_title")
        batch_op.drop_column("sonarr_episode_id")
        batch_op.drop_column("episode")
        batch_op.drop_column("season")
