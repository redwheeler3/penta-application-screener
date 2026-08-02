"""replace sign-in audit with activity timestamps

Stores first and latest authenticated app activity directly on each user. The
event log is removed: activity is intentionally limited to these two timestamps.

Revision ID: a0b1c2d3e4f5
Revises: f9a0b1c2d3e4
Create Date: 2026-08-02
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a0b1c2d3e4f5"
down_revision: str | None = "f9a0b1c2d3e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("first_active_at", sa.DateTime(timezone=True)))
    op.add_column("users", sa.Column("last_active_at", sa.DateTime(timezone=True)))
    op.execute("UPDATE users SET first_active_at = created_at, last_active_at = last_signed_in_at")
    op.drop_index(op.f("ix_user_sign_ins_user_id"), table_name="user_sign_ins")
    op.drop_table("user_sign_ins")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("last_signed_in_at")


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("last_signed_in_at", sa.DateTime(timezone=True)))
    op.execute("UPDATE users SET last_signed_in_at = last_active_at")
    op.create_table(
        "user_sign_ins",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_user_sign_ins_user_id"), "user_sign_ins", ["user_id"])
    with op.batch_alter_table("users") as batch:
        batch.drop_column("last_active_at")
        batch.drop_column("first_active_at")
