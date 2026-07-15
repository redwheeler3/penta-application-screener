"""add private per-member application notes

Revision ID: c3f9a82d1b70
Revises: b2e7d9140c56
Create Date: 2026-07-14 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c3f9a82d1b70"
down_revision: str | None = "b2e7d9140c56"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "application_notes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("application_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("application_id", "user_id"),
    )
    op.create_index("ix_application_notes_application_id", "application_notes", ["application_id"])
    op.create_index("ix_application_notes_user_id", "application_notes", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_application_notes_user_id", table_name="application_notes")
    op.drop_index("ix_application_notes_application_id", table_name="application_notes")
    op.drop_table("application_notes")
