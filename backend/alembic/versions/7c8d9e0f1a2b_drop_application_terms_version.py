"""drop application terms version

Revision ID: 7c8d9e0f1a2b
Revises: 6b7c8d9e0f1a
Create Date: 2026-09-07
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "7c8d9e0f1a2b"
down_revision: str | None = "6b7c8d9e0f1a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("application_versions") as batch:
        batch.drop_column("terms_version")


def downgrade() -> None:
    with op.batch_alter_table("application_versions") as batch:
        batch.add_column(sa.Column("terms_version", sa.String(length=30), nullable=True))
