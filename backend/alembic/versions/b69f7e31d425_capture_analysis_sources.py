"""Capture analysis source identities without guessing historical cohorts.

Revision ID: b69f7e31d425
Revises: a03e1c75b869
"""

import sqlalchemy as sa

from alembic import op

revision = "b69f7e31d425"
down_revision = "a03e1c75b869"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("analyses", sa.Column("source_application_ids", sa.JSON(), nullable=True))
    op.add_column("analyses", sa.Column("pool_text_purged", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("analyses", "pool_text_purged")
    op.drop_column("analyses", "source_application_ids")
