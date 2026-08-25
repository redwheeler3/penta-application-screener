"""allow a new active application after deletion

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c4d5e6f7a8b9"
down_revision: str | None = "b3c4d5e6f7a8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("ix_applications_primary_email", table_name="applications")
    op.create_index(
        "uq_applications_active_primary_email",
        "applications",
        ["primary_email"],
        unique=True,
        sqlite_where=sa.text("deleted_at IS NULL"),
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_applications_active_primary_email", table_name="applications")
    op.create_index(
        "ix_applications_primary_email",
        "applications",
        ["primary_email"],
        unique=True,
    )
