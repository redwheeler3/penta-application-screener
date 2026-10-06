"""Keep content-free note identities so creation retries cannot undo deletion.

Revision ID: e81c9a53f647
Revises: d70b8f42e536
"""
import sqlalchemy as sa
from alembic import op

revision = "e81c9a53f647"
down_revision = "d70b8f42e536"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("application_committee_notes", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    raise RuntimeError("Deleted creation receipts must remain to prevent replay from restoring note text.")
