"""align applicant draft delivery index

Revision ID: e8f9a0b1c2d3
Revises: d6e7f8a9b0c1
Create Date: 2026-08-30
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e8f9a0b1c2d3"
down_revision: str | None = "d6e7f8a9b0c1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE_NAME = "email_deliveries"
LEGACY_INDEX = "ix_email_deliveries_applicant_verification_id"
CURRENT_INDEX = "ix_email_deliveries_applicant_draft_id"


def upgrade() -> None:
    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(TABLE_NAME)}
    if LEGACY_INDEX in indexes:
        op.drop_index(LEGACY_INDEX, table_name=TABLE_NAME)
    if CURRENT_INDEX not in indexes:
        op.create_index(CURRENT_INDEX, TABLE_NAME, ["applicant_draft_id"])


def downgrade() -> None:
    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(TABLE_NAME)}
    if CURRENT_INDEX in indexes:
        op.drop_index(CURRENT_INDEX, table_name=TABLE_NAME)
    if LEGACY_INDEX not in indexes:
        op.create_index(LEGACY_INDEX, TABLE_NAME, ["applicant_draft_id"])
