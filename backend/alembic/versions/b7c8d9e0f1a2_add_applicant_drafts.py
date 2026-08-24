"""add private applicant drafts and applicant access links

Revision ID: b7c8d9e0f1a2
Revises: a6b7c8d9e0f1
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b7c8d9e0f1a2"
down_revision: str | None = "a6b7c8d9e0f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "applicant_drafts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column(
            "intent",
            sa.Enum("save", "submit", name="applicantdraftintent"),
            nullable=False,
        ),
        sa.Column("application_id", sa.Integer(), nullable=True),
        sa.Column("draft_token_hash", sa.String(length=64), nullable=False),
        sa.Column("working_answers", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("saved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("abandon_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_applicant_drafts_email", "applicant_drafts", ["email"])
    op.create_index(
        "ix_applicant_drafts_application_id", "applicant_drafts", ["application_id"]
    )
    op.create_index(
        "ix_applicant_drafts_draft_token_hash",
        "applicant_drafts",
        ["draft_token_hash"],
        unique=True,
    )

    with op.batch_alter_table("magic_link_tokens") as batch:
        batch.drop_constraint("ck_magic_link_token_identity", type_="check")
        batch.add_column(sa.Column("applicant_draft_id", sa.Integer(), nullable=True))
        batch.add_column(
            sa.Column("remember_device", sa.Boolean(), server_default=sa.false(), nullable=False)
        )
        batch.create_foreign_key(
            "fk_magic_link_tokens_applicant_draft_id",
            "applicant_drafts",
            ["applicant_draft_id"],
            ["id"],
        )
        batch.create_index(
            "ix_magic_link_tokens_applicant_draft_id", ["applicant_draft_id"]
        )
        batch.create_check_constraint(
            "ck_magic_link_token_identity",
            "(identity_kind = 'applicant' AND user_id IS NULL AND "
            "((application_id IS NOT NULL AND applicant_draft_id IS NULL) OR "
            "(application_id IS NULL AND applicant_draft_id IS NOT NULL))) "
            "OR (identity_kind = 'committee' AND user_id IS NOT NULL "
            "AND application_id IS NULL AND applicant_draft_id IS NULL)",
        )

    with op.batch_alter_table("email_deliveries") as batch:
        batch.drop_constraint("ck_email_delivery_recipient", type_="check")
        batch.add_column(sa.Column("applicant_draft_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_email_deliveries_applicant_draft_id",
            "applicant_drafts",
            ["applicant_draft_id"],
            ["id"],
        )
        batch.create_index(
            "ix_email_deliveries_applicant_draft_id", ["applicant_draft_id"]
        )
        batch.create_check_constraint(
            "ck_email_delivery_recipient",
            "(recipient_kind = 'applicant' AND user_id IS NULL AND "
            "((application_id IS NOT NULL AND applicant_draft_id IS NULL) OR "
            "(application_id IS NULL AND applicant_draft_id IS NOT NULL))) "
            "OR (recipient_kind = 'committee' AND user_id IS NOT NULL "
            "AND application_id IS NULL AND applicant_draft_id IS NULL)",
        )


def downgrade() -> None:
    with op.batch_alter_table("email_deliveries") as batch:
        batch.drop_constraint("ck_email_delivery_recipient", type_="check")
        batch.drop_index("ix_email_deliveries_applicant_draft_id")
        batch.drop_column("applicant_draft_id")
        batch.create_check_constraint(
            "ck_email_delivery_recipient",
            "(recipient_kind = 'applicant' AND application_id IS NOT NULL AND user_id IS NULL) "
            "OR (recipient_kind = 'committee' AND user_id IS NOT NULL AND application_id IS NULL)",
        )

    with op.batch_alter_table("magic_link_tokens") as batch:
        batch.drop_constraint("ck_magic_link_token_identity", type_="check")
        batch.drop_index("ix_magic_link_tokens_applicant_draft_id")
        batch.drop_column("remember_device")
        batch.drop_column("applicant_draft_id")
        batch.create_check_constraint(
            "ck_magic_link_token_identity",
            "(identity_kind = 'applicant' AND application_id IS NOT NULL AND user_id IS NULL) "
            "OR (identity_kind = 'committee' AND user_id IS NOT NULL AND application_id IS NULL)",
        )

    op.drop_index("ix_applicant_drafts_draft_token_hash", table_name="applicant_drafts")
    op.drop_index("ix_applicant_drafts_application_id", table_name="applicant_drafts")
    op.drop_index("ix_applicant_drafts_email", table_name="applicant_drafts")
    op.drop_table("applicant_drafts")
