"""add pending copy to applicant sessions

Revision ID: 5f6a7b8c9d0e
Revises: 4e5f6a7b8c9d
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "5f6a7b8c9d0e"
down_revision: str | None = "4e5f6a7b8c9d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("browser_sessions") as batch:
        batch.add_column(sa.Column("reconciliation_draft_id", sa.Integer()))
        batch.create_foreign_key(
            "fk_browser_sessions_reconciliation_draft_id",
            "applicant_drafts",
            ["reconciliation_draft_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch.create_index(
            "ix_browser_sessions_reconciliation_draft_id",
            ["reconciliation_draft_id"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("browser_sessions") as batch:
        batch.drop_index("ix_browser_sessions_reconciliation_draft_id")
        batch.drop_constraint(
            "fk_browser_sessions_reconciliation_draft_id", type_="foreignkey"
        )
        batch.drop_column("reconciliation_draft_id")
