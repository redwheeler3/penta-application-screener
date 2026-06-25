"""add sync_run settings_fingerprint

Revision ID: a1f2c3d4e5b6
Revises: 6305b4e2d38b
Create Date: 2026-06-24 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = 'a1f2c3d4e5b6'
down_revision: str | None = '6305b4e2d38b'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Nullable: existing rows predate fingerprinting and read as "can't tell", so
    # the UI leaves Import green for them rather than falsely flagging amber.
    op.add_column(
        'sync_runs',
        sa.Column('settings_fingerprint', sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('sync_runs', 'settings_fingerprint')
