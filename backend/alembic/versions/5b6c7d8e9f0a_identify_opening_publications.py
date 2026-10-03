"""Identify opening publications so uncertain requests can be retried safely.

Revision ID: 5b6c7d8e9f0a
Revises: 9e0f1a2b3c4d
"""

import sqlalchemy as sa

from alembic import op

revision = "5b6c7d8e9f0a"
down_revision = "9e0f1a2b3c4d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("openings", sa.Column("publication_request_id", sa.String(36), nullable=True))
    op.add_column("openings", sa.Column("publication_request", sa.JSON(), nullable=True))
    op.create_index("uq_openings_publication_request_id", "openings", ["publication_request_id"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_openings_publication_request_id", table_name="openings")
    op.drop_column("openings", "publication_request")
    op.drop_column("openings", "publication_request_id")
