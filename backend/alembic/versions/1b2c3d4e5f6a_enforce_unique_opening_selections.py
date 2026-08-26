"""enforce unique opening selections

Revision ID: 1b2c3d4e5f6a
Revises: 0a1b2c3d4e5f
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "1b2c3d4e5f6a"
down_revision: str | None = "0a1b2c3d4e5f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "uq_participations_selected_application",
        "application_participations",
        ["application_id"],
        unique=True,
        sqlite_where=sa.text("outcome = 'selected'"),
    )
    op.create_index(
        "uq_participations_selected_opening",
        "application_participations",
        ["opening_id"],
        unique=True,
        sqlite_where=sa.text("outcome = 'selected'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_participations_selected_opening",
        table_name="application_participations",
    )
    op.drop_index(
        "uq_participations_selected_application",
        table_name="application_participations",
    )
