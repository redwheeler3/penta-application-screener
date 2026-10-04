"""Capture the completed run's final dimension count.

Revision ID: 6c7d8e9f0a1b
Revises: 5b6c7d8e9f0a
"""

import sqlalchemy as sa

from alembic import op

revision = "6c7d8e9f0a1b"
down_revision = "5b6c7d8e9f0a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Historical ledgers have no reliable association with a completed analysis.
    op.add_column("run_cost_ledger", sa.Column("dimension_count", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("run_cost_ledger", "dimension_count")
