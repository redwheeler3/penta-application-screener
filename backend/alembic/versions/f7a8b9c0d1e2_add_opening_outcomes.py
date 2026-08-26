"""add opening outcomes and opening-anchored draft retention

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f7a8b9c0d1e2"
down_revision: str | None = "e6f7a8b9c0d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("applicant_drafts") as batch:
        batch.add_column(sa.Column("retention_due_on", sa.Date(), nullable=True))
    op.execute(
        "UPDATE applicant_drafts SET retention_due_on = date(abandon_after, '+335 days')"
    )
    with op.batch_alter_table("applicant_drafts") as batch:
        batch.alter_column("retention_due_on", nullable=False)
        batch.drop_column("abandon_after")

    with op.batch_alter_table("application_participations") as batch:
        batch.add_column(
            sa.Column(
                "outcome",
                sa.Enum("selected", "unsuccessful", name="openingoutcome"),
                nullable=True,
            )
        )
        batch.add_column(
            sa.Column("outcome_decided_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch.add_column(
            sa.Column("outcome_decided_by_user_id", sa.Integer(), nullable=True)
        )
        batch.add_column(
            sa.Column("unsuccessful_notified_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch.create_foreign_key(
            "fk_application_participations_outcome_user",
            "users",
            ["outcome_decided_by_user_id"],
            ["id"],
        )
        batch.create_index(
            "ix_application_participations_outcome", ["outcome"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("application_participations") as batch:
        batch.drop_index("ix_application_participations_outcome")
        batch.drop_constraint(
            "fk_application_participations_outcome_user", type_="foreignkey"
        )
        batch.drop_column("unsuccessful_notified_at")
        batch.drop_column("outcome_decided_by_user_id")
        batch.drop_column("outcome_decided_at")
        batch.drop_column("outcome")

    with op.batch_alter_table("applicant_drafts") as batch:
        batch.add_column(sa.Column("abandon_after", sa.DateTime(), nullable=True))
    op.execute(
        "UPDATE applicant_drafts SET abandon_after = "
        "datetime(retention_due_on, '-335 days')"
    )
    with op.batch_alter_table("applicant_drafts") as batch:
        batch.alter_column("abandon_after", nullable=False)
        batch.drop_column("retention_due_on")
