"""retain the session that initiates an applicant email change

Revision ID: c8d9e0f1a2b3
Revises: b7c8d9e0f1a2
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c8d9e0f1a2b3"
down_revision: str | None = "b7c8d9e0f1a2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("magic_link_tokens") as batch:
        batch.add_column(sa.Column("initiating_session_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_magic_link_tokens_initiating_session_id",
            "browser_sessions",
            ["initiating_session_id"],
            ["id"],
        )
        batch.create_index(
            "ix_magic_link_tokens_initiating_session_id", ["initiating_session_id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("magic_link_tokens") as batch:
        batch.drop_index("ix_magic_link_tokens_initiating_session_id")
        batch.drop_column("initiating_session_id")
