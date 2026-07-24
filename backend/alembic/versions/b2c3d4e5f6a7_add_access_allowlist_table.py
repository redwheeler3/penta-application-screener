"""add the access_allowlist table (M15 slice 1a)

The access gate for going multi-user: an OAuth login is admitted only if its email
matches an allowlist entry, and the resulting user takes the entry's role. Initial
admins are seeded from a config file at startup (idempotent), so this migration only
creates the empty table.

Purely additive — a brand-new table, so no batch_alter_table and nothing to
backfill; applies cleanly to existing data with ``alembic upgrade head`` (no reset).
Reversible: the downgrade drops the table.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-07-24
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "access_allowlist",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column(
            "role",
            sa.Enum("admin", "member", name="userrole"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_access_allowlist_email"),
        "access_allowlist",
        ["email"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_access_allowlist_email"), table_name="access_allowlist")
    op.drop_table("access_allowlist")
