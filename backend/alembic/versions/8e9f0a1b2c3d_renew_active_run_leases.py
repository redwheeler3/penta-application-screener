"""Renew live runs independently of their acquisition identity.

Revision ID: 8e9f0a1b2c3d
Revises: 7d8e9f0a1b2c
"""

import sqlalchemy as sa

from alembic import op

revision = "8e9f0a1b2c3d"
down_revision = "7d8e9f0a1b2c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("run_lock", sa.Column("renewed_at", sa.DateTime(timezone=True), nullable=True))
    op.execute(sa.text("UPDATE run_lock SET renewed_at = held_since WHERE holder_user_id IS NOT NULL"))


def downgrade() -> None:
    op.drop_column("run_lock", "renewed_at")
