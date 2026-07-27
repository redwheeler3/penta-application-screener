"""add user sign-in audit

Stores one event for each successful allowlisted Google login and a direct
last-sign-in timestamp on the user. Existing accounts keep their first-login
timestamp from ``users.created_at`` and their best available last-login value
from the pre-existing generic ``users.updated_at``; sign-in counts begin with
new events after this migration.

Revision ID: e7f8a9b0c1d2
Revises: 7fd71ed7b2ac
Create Date: 2026-07-26
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e7f8a9b0c1d2"
down_revision: str | None = "7fd71ed7b2ac"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("last_signed_in_at", sa.DateTime(timezone=True)))
    op.execute("UPDATE users SET last_signed_in_at = updated_at")
    op.create_table(
        "user_sign_ins",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_user_sign_ins_user_id"), "user_sign_ins", ["user_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_user_sign_ins_user_id"), table_name="user_sign_ins")
    op.drop_table("user_sign_ins")
    op.drop_column("users", "last_signed_in_at")
