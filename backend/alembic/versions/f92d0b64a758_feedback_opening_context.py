"""Record feedback opening and retained-review context.

Revision ID: f92d0b64a758
Revises: e81c9a53f647
"""

import sqlalchemy as sa

from alembic import op

revision = "f92d0b64a758"
down_revision = "e81c9a53f647"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("feedback", sa.Column("opening_id", sa.Integer(), nullable=True))
    op.add_column("feedback", sa.Column("retained_review", sa.Boolean(), nullable=False, server_default="0"))


def downgrade():
    op.drop_column("feedback", "retained_review")
    op.drop_column("feedback", "opening_id")
