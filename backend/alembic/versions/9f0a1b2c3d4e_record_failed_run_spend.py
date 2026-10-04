"""Record failed attempts and explicit cache-work units without guessing historical counts.

Revision ID: 9f0a1b2c3d4e
Revises: 8e9f0a1b2c3d
"""

import sqlalchemy as sa

from alembic import op

revision = "9f0a1b2c3d4e"
down_revision = "8e9f0a1b2c3d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("run_cost_ledger", sa.Column("status", sa.String(20), nullable=False, server_default="completed"))
    op.add_column("run_cost_ledger", sa.Column("failed_pass", sa.String(80), nullable=True))
    op.add_column("run_cost_ledger", sa.Column("failure_type", sa.String(120), nullable=True))
    op.add_column("run_pass_cost", sa.Column("fresh_units", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("run_pass_cost", "fresh_units")
    op.drop_column("run_cost_ledger", "failure_type")
    op.drop_column("run_cost_ledger", "failed_pass")
    op.drop_column("run_cost_ledger", "status")
