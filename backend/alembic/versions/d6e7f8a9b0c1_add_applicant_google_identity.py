"""add applicant Google identity

Revision ID: d6e7f8a9b0c1
Revises: c5d6e7f8a9b0
Create Date: 2026-08-29
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d6e7f8a9b0c1"
down_revision: str | None = "c5d6e7f8a9b0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("applications", sa.Column("google_subject", sa.String(length=255)))
    op.create_index(
        "ix_applications_google_subject",
        "applications",
        ["google_subject"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_applications_google_subject", table_name="applications")
    op.drop_column("applications", "google_subject")
