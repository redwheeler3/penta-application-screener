"""add duration + failed-call metrics to run_pass_cost (M13 Pillar 3)

Revision ID: b2e7d9140c56
Revises: a1f4c7e29b83
Create Date: 2026-07-12 05:00:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = 'b2e7d9140c56'
down_revision: str | None = 'a1f4c7e29b83'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Operational metrics per pass: wall-clock latency and error count. server_default 0
    # so pre-Pillar-3 rows read as "unmeasured", not null.
    op.add_column('run_pass_cost', sa.Column('duration_ms', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('run_pass_cost', sa.Column('failed_calls', sa.Integer(), nullable=False, server_default='0'))


def downgrade() -> None:
    op.drop_column('run_pass_cost', 'failed_calls')
    op.drop_column('run_pass_cost', 'duration_ms')
