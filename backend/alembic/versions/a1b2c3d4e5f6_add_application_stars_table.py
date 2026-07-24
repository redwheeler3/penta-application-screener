"""add the application_stars table (per-member favourites)

A member can star (favourite) an applicant as a personal working aid — a bookmark
plus a "show only favourites" list filter — with no effect on ranking, eligibility,
or reports. Mirrors ``application_notes``: per (application, user), private to the
member. The row's existence IS the state (starred when present), so there is no
boolean column; unstarring deletes the row.

Purely additive — a brand-new table, so no ``batch_alter_table`` and nothing to
backfill; it applies cleanly to existing data with ``alembic upgrade head`` (no
reset). Reversible: the downgrade drops the table.

Revision ID: a1b2c3d4e5f6
Revises: b3e2f9a4c1d7
Create Date: 2026-07-23
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "b3e2f9a4c1d7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "application_stars",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("application_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
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
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("application_id", "user_id"),
    )
    op.create_index(
        op.f("ix_application_stars_application_id"),
        "application_stars",
        ["application_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_application_stars_user_id"),
        "application_stars",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_application_stars_user_id"), table_name="application_stars")
    op.drop_index(
        op.f("ix_application_stars_application_id"), table_name="application_stars"
    )
    op.drop_table("application_stars")
