"""preserve first vacancy consent

Revision ID: c5d6e7f8a9b0
Revises: b4c5d6e7f8a9
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c5d6e7f8a9b0"
down_revision: str | None = "b4c5d6e7f8a9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("vacancy_subscriptions") as batch:
        batch.add_column(
            sa.Column("first_consented_at", sa.DateTime(timezone=True), nullable=True)
        )
    op.execute(
        sa.text(
            "UPDATE vacancy_subscriptions "
            "SET first_consented_at = consented_at"
        )
    )
    with op.batch_alter_table("vacancy_subscriptions") as batch:
        batch.alter_column(
            "first_consented_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        )


def downgrade() -> None:
    with op.batch_alter_table("vacancy_subscriptions") as batch:
        batch.drop_column("first_consented_at")
