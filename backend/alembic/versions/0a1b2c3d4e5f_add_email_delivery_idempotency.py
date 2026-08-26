"""add email delivery idempotency

Revision ID: 0a1b2c3d4e5f
Revises: f7a8b9c0d1e2
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0a1b2c3d4e5f"
down_revision: str | None = "f7a8b9c0d1e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("email_deliveries") as batch:
        batch.add_column(sa.Column("idempotency_key", sa.String(length=120)))
        batch.create_index(
            "ix_email_deliveries_idempotency_key",
            ["idempotency_key"],
            unique=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("email_deliveries") as batch:
        batch.drop_index("ix_email_deliveries_idempotency_key")
        batch.drop_column("idempotency_key")
