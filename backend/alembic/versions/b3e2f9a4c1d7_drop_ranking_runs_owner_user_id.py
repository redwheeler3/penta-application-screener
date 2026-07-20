"""drop the dead ranking_runs.owner_user_id column

M14 follow-up. ``owner_user_id`` (+ its ``owner`` relationship) was carried through the
schema history but never written or read — always NULL. The M14 Phase 5 split dropped the
other vestigial columns (name/status) but this one survived. Drop it now.

Reversible: the downgrade re-adds the nullable FK column (it was always NULL, so no data is
lost either direction). Uses batch_alter_table — SQLite drops a column by recreating the
table, and the column carries a users.id foreign key. Back up the .db before running.

Revision ID: b3e2f9a4c1d7
Revises: c84f612585ea
Create Date: 2026-07-20
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b3e2f9a4c1d7"
down_revision: str | None = "c84f612585ea"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("ranking_runs") as batch:
        batch.drop_column("owner_user_id")


def downgrade() -> None:
    # Re-add the nullable FK exactly as the baseline created it. It was always NULL, so
    # there is nothing to backfill.
    with op.batch_alter_table("ranking_runs") as batch:
        batch.add_column(sa.Column("owner_user_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_ranking_runs_owner_user_id_users", "users", ["owner_user_id"], ["id"]
        )
