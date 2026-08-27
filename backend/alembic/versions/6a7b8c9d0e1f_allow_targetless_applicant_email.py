"""allow targetless applicant email delivery

Revision ID: 6a7b8c9d0e1f
Revises: 5f6a7b8c9d0e
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "6a7b8c9d0e1f"
down_revision: str | None = "5f6a7b8c9d0e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("email_deliveries") as batch:
        batch.drop_constraint("ck_email_delivery_recipient", type_="check")
        batch.add_column(sa.Column("recipient_email", sa.String(length=320)))
        batch.create_check_constraint(
            "ck_email_delivery_recipient",
            "(recipient_kind = 'applicant' AND user_id IS NULL AND "
            "((application_id IS NOT NULL AND applicant_draft_id IS NULL) OR "
            "(application_id IS NULL AND applicant_draft_id IS NOT NULL) OR "
            "(application_id IS NULL AND applicant_draft_id IS NULL))) "
            "OR (recipient_kind = 'committee' AND user_id IS NOT NULL "
            "AND application_id IS NULL AND applicant_draft_id IS NULL)",
        )


def downgrade() -> None:
    with op.batch_alter_table("email_deliveries") as batch:
        batch.drop_constraint("ck_email_delivery_recipient", type_="check")
        batch.drop_column("recipient_email")
        batch.create_check_constraint(
            "ck_email_delivery_recipient",
            "(recipient_kind = 'applicant' AND user_id IS NULL AND "
            "((application_id IS NOT NULL AND applicant_draft_id IS NULL) OR "
            "(application_id IS NULL AND applicant_draft_id IS NOT NULL))) "
            "OR (recipient_kind = 'committee' AND user_id IS NOT NULL "
            "AND application_id IS NULL AND applicant_draft_id IS NULL)",
        )
