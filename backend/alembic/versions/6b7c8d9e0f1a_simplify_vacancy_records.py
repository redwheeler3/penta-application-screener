"""simplify vacancy records

Revision ID: 6b7c8d9e0f1a
Revises: 5a6b7c8d9e0f
Create Date: 2026-09-07
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "6b7c8d9e0f1a"
down_revision: str | None = "5a6b7c8d9e0f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM email_deliveries "
            "WHERE message_kind = 'vacancy_opening' AND state = 'accepted'"
        )
    )
    op.drop_table("vacancy_consent_receipts")
    op.drop_table("vacancy_subscription_audits")
    with op.batch_alter_table("vacancy_subscriptions") as batch:
        batch.drop_index("ix_vacancy_subscriptions_managed_by_user_id")
        batch.drop_column("consent_version")
        batch.drop_column("managed_by_user_id")


def downgrade() -> None:
    with op.batch_alter_table("vacancy_subscriptions") as batch:
        batch.add_column(sa.Column("consent_version", sa.String(length=30), nullable=True))
        batch.add_column(sa.Column("managed_by_user_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_vacancy_subscriptions_managed_by_user_id_users",
            "users",
            ["managed_by_user_id"],
            ["id"],
        )
        batch.create_index(
            "ix_vacancy_subscriptions_managed_by_user_id",
            ["managed_by_user_id"],
        )
    op.create_table(
        "vacancy_consent_receipts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("subscription_id", sa.Integer(), nullable=False),
        sa.Column("unit_sizes", sa.JSON(), nullable=False),
        sa.Column("consented_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consent_version", sa.String(length=30), nullable=True),
        sa.Column("source", sa.String(length=120), nullable=False),
        sa.Column("fulfilled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retain_until", sa.Date(), nullable=False),
        sa.Column("email_delivery_id", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_vacancy_consent_receipts_retain_until",
        "vacancy_consent_receipts",
        ["retain_until"],
    )
    op.create_table(
        "vacancy_subscription_audits",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("subscription_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("source", sa.String(length=120), nullable=False),
        sa.Column("acted_by_user_id", sa.Integer(), nullable=False),
        sa.Column("acted_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["acted_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_vacancy_subscription_audits_subscription_id",
        "vacancy_subscription_audits",
        ["subscription_id"],
    )
    op.create_index(
        "ix_vacancy_subscription_audits_acted_by_user_id",
        "vacancy_subscription_audits",
        ["acted_by_user_id"],
    )
