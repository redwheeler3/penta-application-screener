"""add email retry intents

Revision ID: 4e5f6a7b8c9d
Revises: 3d4e5f6a7b8c
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "4e5f6a7b8c9d"
down_revision: str | None = "3d4e5f6a7b8c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("email_deliveries") as batch:
        batch.add_column(sa.Column("retry_intent", sa.JSON()))
        batch.add_column(
            sa.Column(
                "quota_blocked",
                sa.Boolean(),
                server_default="0",
                nullable=False,
            )
        )
        batch.create_index(
            "ix_email_deliveries_quota_blocked", ["quota_blocked"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("email_deliveries") as batch:
        batch.drop_index("ix_email_deliveries_quota_blocked")
        batch.drop_column("quota_blocked")
        batch.drop_column("retry_intent")
