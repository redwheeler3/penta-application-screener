"""drop declaration acceptance timestamps

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e6f7a8b9c0d1"
down_revision: str | None = "d5e6f7a8b9c0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("application_versions") as batch:
        batch.drop_column("declaration_accepted_at")
    with op.batch_alter_table("applications") as batch:
        batch.drop_column("declaration_accepted_at")


def downgrade() -> None:
    with op.batch_alter_table("applications") as batch:
        batch.add_column(
            sa.Column("declaration_accepted_at", sa.DateTime(timezone=True), nullable=True)
        )
    op.execute(
        "UPDATE applications SET declaration_accepted_at = submitted_at "
        "WHERE submitted_at IS NOT NULL"
    )

    with op.batch_alter_table("application_versions") as batch:
        batch.add_column(
            sa.Column("declaration_accepted_at", sa.DateTime(timezone=True), nullable=True)
        )
    op.execute("UPDATE application_versions SET declaration_accepted_at = submitted_at")
    with op.batch_alter_table("application_versions") as batch:
        batch.alter_column("declaration_accepted_at", nullable=False)
