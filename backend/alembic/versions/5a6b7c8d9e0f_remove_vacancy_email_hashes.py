"""remove vacancy email hashes

Revision ID: 5a6b7c8d9e0f
Revises: 4f5a6b7c8d9e
Create Date: 2026-09-07
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "5a6b7c8d9e0f"
down_revision: str | None = "4f5a6b7c8d9e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("vacancy_consent_receipts") as batch:
        batch.drop_index("ix_vacancy_consent_receipts_email_hash")
        batch.drop_column("email_hash")
    with op.batch_alter_table("vacancy_subscription_audits") as batch:
        batch.drop_index("ix_vacancy_subscription_audits_email_hash")
        batch.drop_column("email_hash")


def downgrade() -> None:
    for table_name, index_name in (
        (
            "vacancy_consent_receipts",
            "ix_vacancy_consent_receipts_email_hash",
        ),
        (
            "vacancy_subscription_audits",
            "ix_vacancy_subscription_audits_email_hash",
        ),
    ):
        with op.batch_alter_table(table_name) as batch:
            batch.add_column(
                sa.Column("email_hash", sa.String(length=64), nullable=True)
            )
        op.execute(sa.text(f"UPDATE {table_name} SET email_hash = 'removed'"))
        with op.batch_alter_table(table_name) as batch:
            batch.alter_column("email_hash", nullable=False)
            batch.create_index(index_name, ["email_hash"])
