"""Identify committee-note creation attempts across lost acknowledgements.

Revision ID: c69a7e31d425
Revises: b58f6d20c314
"""
import sqlalchemy as sa

from alembic import op

revision = "c69a7e31d425"
down_revision = "b58f6d20c314"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("application_committee_notes", sa.Column("creation_key", sa.String(36), nullable=True))
    op.create_index("uq_committee_note_creation", "application_committee_notes",
                    ["application_id", "author_user_id", "creation_key"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_committee_note_creation", table_name="application_committee_notes")
    op.drop_column("application_committee_notes", "creation_key")
