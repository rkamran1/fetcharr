"""sites, their encrypted cookie files, and which site a job uses

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Requirements §8, frozen here: later changes to the built-ins get their own revision.
BUILTIN_SITES = [
    {
        "key": "youtube",
        "label": "YouTube",
        "domains": ["youtube.com", "youtu.be", "youtube-nocookie.com", "google.com"],
        "builtin": True,
    },
    {
        "key": "bilibili",
        "label": "Bilibili",
        "domains": ["bilibili.com", "bilibili.tv", "b23.tv"],
        "builtin": True,
    },
    {
        "key": "dailymotion",
        "label": "Dailymotion",
        "domains": ["dailymotion.com", "dai.ly"],
        "builtin": True,
    },
]


def upgrade() -> None:
    sites = op.create_table(
        "sites",
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("domains", sa.JSON(), nullable=False),
        sa.Column("builtin", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_table(
        "site_cookies",
        sa.Column("site_key", sa.String(), nullable=False),
        sa.Column("enc_blob", sa.String(), nullable=False),
        sa.Column("cookie_count", sa.Integer(), nullable=False),
        sa.Column("earliest_expiry", sa.DateTime(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("flagged_invalid", sa.Boolean(), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["site_key"], ["sites.key"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("site_key"),
    )
    op.bulk_insert(sites, BUILTIN_SITES)
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("site_key", sa.String(), nullable=True))
        batch_op.add_column(
            sa.Column("use_cookies", sa.Boolean(), nullable=False, server_default=sa.true())
        )


def downgrade() -> None:
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.drop_column("use_cookies")
        batch_op.drop_column("site_key")
    op.drop_table("site_cookies")
    op.drop_table("sites")
