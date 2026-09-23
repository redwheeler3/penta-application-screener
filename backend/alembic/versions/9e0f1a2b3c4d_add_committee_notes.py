"""add committee notes

Revision ID: 9e0f1a2b3c4d
Revises: 8d9e0f1a2b3c
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "9e0f1a2b3c4d"
down_revision: str | None = "8d9e0f1a2b3c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "application_committee_notes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("application_id", sa.Integer(), nullable=False),
        sa.Column("author_user_id", sa.Integer(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["application_id"], ["applications.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["author_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_application_committee_notes_application_id"),
        "application_committee_notes",
        ["application_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_application_committee_notes_author_user_id"),
        "application_committee_notes",
        ["author_user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_application_committee_notes_author_user_id"),
        table_name="application_committee_notes",
    )
    op.drop_index(
        op.f("ix_application_committee_notes_application_id"),
        table_name="application_committee_notes",
    )
    op.drop_table("application_committee_notes")
