"""settings table and the job import columns

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "settings",
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("is_secret", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("collision_policy", sa.String(), nullable=False, server_default="keep_both")
        )
        batch_op.add_column(sa.Column("import_command_id", sa.String(), nullable=True))
        batch_op.add_column(
            sa.Column("import_attempts", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.add_column(sa.Column("import_detail", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("imported_path", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("imported_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.drop_column("imported_at")
        batch_op.drop_column("imported_path")
        batch_op.drop_column("import_detail")
        batch_op.drop_column("import_attempts")
        batch_op.drop_column("import_command_id")
        batch_op.drop_column("collision_policy")

    op.drop_table("settings")
