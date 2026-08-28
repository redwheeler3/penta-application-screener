"""add direct-selection openings

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b4c5d6e7f8a9"
down_revision: str | None = "a3b4c5d6e7f8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("openings") as batch:
        batch.add_column(
            sa.Column(
                "intake_mode",
                sa.Enum(
                    "applications",
                    "direct_selection",
                    name="openingintakemode",
                ),
                server_default="applications",
                nullable=False,
            )
        )
        batch.alter_column(
            "application_open_date",
            existing_type=sa.Date(),
            nullable=True,
        )
        batch.alter_column(
            "application_close_date",
            existing_type=sa.Date(),
            nullable=True,
        )


def downgrade() -> None:
    direct_count = op.get_bind().scalar(
        sa.text("SELECT COUNT(*) FROM openings WHERE intake_mode = 'direct_selection'")
    )
    if direct_count:
        raise RuntimeError("Delete direct-selection openings before downgrading this migration.")
    with op.batch_alter_table("openings") as batch:
        batch.alter_column(
            "application_close_date",
            existing_type=sa.Date(),
            nullable=False,
        )
        batch.alter_column(
            "application_open_date",
            existing_type=sa.Date(),
            nullable=False,
        )
        batch.drop_column("intake_mode")
