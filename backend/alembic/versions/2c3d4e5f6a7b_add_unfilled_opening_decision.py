"""add unfilled opening decision

Revision ID: 2c3d4e5f6a7b
Revises: 1b2c3d4e5f6a
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "2c3d4e5f6a7b"
down_revision: str | None = "1b2c3d4e5f6a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("openings") as batch:
        batch.add_column(
            sa.Column("no_household_selected_at", sa.DateTime(timezone=True))
        )
        batch.add_column(
            sa.Column("no_household_selected_by_user_id", sa.Integer())
        )
        batch.create_foreign_key(
            "fk_openings_no_household_selected_by_user",
            "users",
            ["no_household_selected_by_user_id"],
            ["id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("openings") as batch:
        batch.drop_constraint(
            "fk_openings_no_household_selected_by_user", type_="foreignkey"
        )
        batch.drop_column("no_household_selected_by_user_id")
        batch.drop_column("no_household_selected_at")
