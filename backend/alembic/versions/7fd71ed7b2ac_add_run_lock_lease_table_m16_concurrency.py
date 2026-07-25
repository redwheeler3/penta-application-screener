"""add run_lock lease table (M16 concurrency)

Additive: one ``run_lock`` table holding a single lease row (id=1) that serializes the
expensive AI runs (Screen / full Rank / score-current) across members. Claimed by an atomic
conditional UPDATE and released in the run stream's finally; ``held_since`` backs a TTL steal
so a crashed run can't wedge the workflow (see ``services/run_lock``). The single row is
SEEDED here so the claim UPDATE always has a row to match. Downgrade drops the table.
Back up the .db before running.

Revision ID: 7fd71ed7b2ac
Revises: 282b33a17310
Create Date: 2026-07-24 21:06:53.477144
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "7fd71ed7b2ac"
down_revision: str | None = "282b33a17310"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    run_lock = op.create_table(
        "run_lock",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("holder_user_id", sa.Integer(), nullable=True),
        sa.Column("kind", sa.String(length=20), nullable=True),
        sa.Column("held_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False,
        ),
        sa.ForeignKeyConstraint(["holder_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    # Seed the single lease row, free (no holder). The claim is an UPDATE, so this row must
    # exist for a run to ever acquire the lock.
    op.bulk_insert(run_lock, [{"id": 1, "holder_user_id": None, "kind": None, "held_since": None}])


def downgrade() -> None:
    op.drop_table("run_lock")
