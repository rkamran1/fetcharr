"""requests.naming: the naming templates and colon mode a request was created with

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | Sequence[str] | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A plain ADD COLUMN, never batch mode: rebuilding `requests` would drop 0009's FTS triggers.
    op.add_column("requests", sa.Column("naming", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("requests", "naming")
