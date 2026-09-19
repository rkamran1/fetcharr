"""inspections: cached yt-dlp inspect results

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "inspections",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("site_key", sa.String(), nullable=True),
        sa.Column("info", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sqlite_autoincrement=True,
    )
    with op.batch_alter_table("inspections") as batch_op:
        batch_op.create_index("ix_inspections_url", ["url"], unique=False)
        batch_op.create_index("ix_inspections_expires_at", ["expires_at"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("inspections") as batch_op:
        batch_op.drop_index("ix_inspections_expires_at")
        batch_op.drop_index("ix_inspections_url")
    op.drop_table("inspections")
