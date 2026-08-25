"""record opening selections on application versions

Revision ID: f1a2b3c4d5e6
Revises: e0f1a2b3c4d5
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f1a2b3c4d5e6"
down_revision: str | None = "e0f1a2b3c4d5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("application_versions") as batch:
        batch.add_column(
            sa.Column(
                "selected_opening_ids",
                sa.JSON(),
                server_default="[]",
                nullable=False,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("application_versions") as batch:
        batch.drop_column("selected_opening_ids")
