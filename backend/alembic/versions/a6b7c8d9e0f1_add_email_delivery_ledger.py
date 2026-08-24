"""add email delivery ledger

Revision ID: a6b7c8d9e0f1
Revises: f5a6b7c8d9e0
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a6b7c8d9e0f1"
down_revision: str | None = "f5a6b7c8d9e0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "email_deliveries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("message_kind", sa.String(length=80), nullable=False),
        sa.Column(
            "recipient_kind",
            sa.Enum("applicant", "committee", name="passwordlessidentitykind"),
            nullable=False,
        ),
        sa.Column("application_id", sa.Integer(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("magic_link_token_id", sa.Integer(), nullable=True),
        sa.Column(
            "state",
            sa.Enum(
                "queued",
                "accepted",
                "failed",
                "bounced",
                "complained",
                name="emaildeliverystate",
            ),
            nullable=False,
        ),
        sa.Column("provider_message_id", sa.String(length=255), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "(recipient_kind = 'applicant' AND application_id IS NOT NULL AND user_id IS NULL) "
            "OR (recipient_kind = 'committee' AND user_id IS NOT NULL AND application_id IS NULL)",
            name="ck_email_delivery_recipient",
        ),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"]),
        sa.ForeignKeyConstraint(["magic_link_token_id"], ["magic_link_tokens.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "message_kind",
        "recipient_kind",
        "application_id",
        "user_id",
        "magic_link_token_id",
        "state",
        "provider_message_id",
    ):
        op.create_index(f"ix_email_deliveries_{column}", "email_deliveries", [column])


def downgrade() -> None:
    for column in reversed(
        (
            "message_kind",
            "recipient_kind",
            "application_id",
            "user_id",
            "magic_link_token_id",
            "state",
            "provider_message_id",
        )
    ):
        op.drop_index(f"ix_email_deliveries_{column}", table_name="email_deliveries")
    op.drop_table("email_deliveries")
