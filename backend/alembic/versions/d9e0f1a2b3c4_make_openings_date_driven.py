"""make opening availability date-driven

Revision ID: d9e0f1a2b3c4
Revises: c8d9e0f1a2b3
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d9e0f1a2b3c4"
down_revision: str | None = "c8d9e0f1a2b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("openings") as batch:
        batch.add_column(sa.Column("application_open_date", sa.Date(), nullable=True))
        batch.add_column(sa.Column("application_close_date", sa.Date(), nullable=True))
        batch.add_column(sa.Column("published_at", sa.DateTime(timezone=True), nullable=True))
    op.execute(
        "UPDATE openings SET "
        "application_open_date = date(application_deadline), "
        "application_close_date = date(application_deadline), "
        "published_at = CURRENT_TIMESTAMP"
    )
    with op.batch_alter_table("openings") as batch:
        batch.alter_column("application_open_date", nullable=False)
        batch.alter_column("application_close_date", nullable=False)
        batch.create_index("ix_openings_published_at", ["published_at"])
        batch.drop_column("title")
        batch.drop_column("description")
        batch.drop_column("application_deadline")
        batch.drop_index("ix_openings_status")
        batch.drop_column("status")


def downgrade() -> None:
    with op.batch_alter_table("openings") as batch:
        batch.add_column(sa.Column("title", sa.String(length=255), nullable=True))
        batch.add_column(sa.Column("description", sa.Text(), nullable=True))
        batch.add_column(
            sa.Column("application_deadline", sa.DateTime(timezone=True), nullable=True)
        )
        batch.add_column(
            sa.Column(
                "status",
                sa.Enum("open", "closed", name="openingstatus"),
                nullable=True,
            )
        )
    op.execute(
        "UPDATE openings SET "
        "title = unit_size_bedrooms || '-bedroom opening', "
        "application_deadline = application_close_date || ' 23:59:59', "
        "status = CASE WHEN published_at IS NULL THEN 'closed' ELSE 'open' END"
    )
    with op.batch_alter_table("openings") as batch:
        batch.alter_column("title", nullable=False)
        batch.alter_column("application_deadline", nullable=False)
        batch.alter_column("status", nullable=False)
        batch.create_index("ix_openings_status", ["status"])
        batch.drop_index("ix_openings_published_at")
        batch.drop_column("published_at")
        batch.drop_column("application_close_date")
        batch.drop_column("application_open_date")
