"""drop sync_runs.eligible_count / filtered_out_count (dead since M15 1c)

These two columns are latent dead weight. Import computed them (a hard-filter pass over every
applicant at sync time) and the API copied them into the sync response, but nothing has
displayed them since eligibility went compute-on-read in M15 1c: the sync toast shows only
row/imported/updated/unchanged, and the dashboard's eligible/filtered counts come from the
on-read per-member computation, not from SyncRun. Import no longer evaluates eligibility at
all, so there is nothing to populate them with either. Drop them.

Reversible: downgrade re-adds both columns (default 0). Historical per-sync counts are NOT
reconstructed — they were a committee-default snapshot at each import, unrecoverable after the
fact — so downgraded rows carry 0. Back up the .db before running.

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-07-24
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c9d0e1f2a3b4"
down_revision: str | None = "b8c9d0e1f2a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("sync_runs") as batch:
        batch.drop_column("eligible_count")
        batch.drop_column("filtered_out_count")


def downgrade() -> None:
    with op.batch_alter_table("sync_runs") as batch:
        batch.add_column(
            sa.Column("eligible_count", sa.Integer(), nullable=False, server_default="0")
        )
        batch.add_column(
            sa.Column("filtered_out_count", sa.Integer(), nullable=False, server_default="0")
        )
