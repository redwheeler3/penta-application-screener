"""drop browser session recency

Revision ID: 7b8c9d0e1f2a
Revises: 6a7b8c9d0e1f
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "7b8c9d0e1f2a"
down_revision: str | None = "6a7b8c9d0e1f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("browser_sessions") as batch:
        batch.drop_column("recently_authenticated_at")


def downgrade() -> None:
    with op.batch_alter_table("browser_sessions") as batch:
        batch.add_column(
            sa.Column(
                "recently_authenticated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            )
        )
