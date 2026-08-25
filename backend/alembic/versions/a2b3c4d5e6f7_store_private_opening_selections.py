"""store opening selections with private working copies

Revision ID: a2b3c4d5e6f7
Revises: f1a2b3c4d5e6
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a2b3c4d5e6f7"
down_revision: str | None = "f1a2b3c4d5e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("applications") as batch:
        batch.add_column(sa.Column("working_opening_ids", sa.JSON(), nullable=True))
    with op.batch_alter_table("applicant_drafts") as batch:
        batch.add_column(sa.Column("working_opening_ids", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("applicant_drafts") as batch:
        batch.drop_column("working_opening_ids")
    with op.batch_alter_table("applications") as batch:
        batch.drop_column("working_opening_ids")
