"""publish existing opening drafts

Revision ID: 9d0e1f2a3b4c
Revises: 8c9d0e1f2a3b
"""

from collections.abc import Sequence

from alembic import op

revision: str = "9d0e1f2a3b4c"
down_revision: str | None = "8c9d0e1f2a3b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "UPDATE openings SET published_at = created_at, "
        "application_open_date = date(created_at) WHERE published_at IS NULL"
    )


def downgrade() -> None:
    """Publication cannot be reversed because prior drafts are no longer distinguishable."""
