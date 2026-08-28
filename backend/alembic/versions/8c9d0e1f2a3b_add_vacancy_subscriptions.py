"""add vacancy subscriptions

Revision ID: 8c9d0e1f2a3b
Revises: 7b8c9d0e1f2a
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "8c9d0e1f2a3b"
down_revision: str | None = "7b8c9d0e1f2a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "vacancy_subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("wants_one_bedroom", sa.Boolean(), nullable=False),
        sa.Column("wants_two_bedroom", sa.Boolean(), nullable=False),
        sa.Column("wants_three_bedroom", sa.Boolean(), nullable=False),
        sa.Column("consented_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(length=120), nullable=False),
        sa.Column("managed_by_user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "wants_one_bedroom OR wants_two_bedroom OR wants_three_bedroom",
            name="ck_vacancy_subscription_has_unit_size",
        ),
    )
    op.create_index("ix_vacancy_subscriptions_email", "vacancy_subscriptions", ["email"], unique=True)
    op.create_index("ix_vacancy_subscriptions_consented_at", "vacancy_subscriptions", ["consented_at"])
    op.create_index("ix_vacancy_subscriptions_managed_by_user_id", "vacancy_subscriptions", ["managed_by_user_id"])
    op.create_table(
        "vacancy_subscription_audits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("subscription_id", sa.Integer()),
        sa.Column("email_hash", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("source", sa.String(length=120), nullable=False),
        sa.Column("acted_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("acted_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_vacancy_subscription_audits_subscription_id", "vacancy_subscription_audits", ["subscription_id"])
    op.create_index("ix_vacancy_subscription_audits_email_hash", "vacancy_subscription_audits", ["email_hash"])
    op.create_index("ix_vacancy_subscription_audits_acted_by_user_id", "vacancy_subscription_audits", ["acted_by_user_id"])


def downgrade() -> None:
    op.drop_table("vacancy_subscription_audits")
    op.drop_table("vacancy_subscriptions")
