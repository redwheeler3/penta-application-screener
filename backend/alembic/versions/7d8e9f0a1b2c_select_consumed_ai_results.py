"""Reference the AI results selected for display, including cache reuse.

Revision ID: 7d8e9f0a1b2c
Revises: 6c7d8e9f0a1b
"""

import sqlalchemy as sa

from alembic import op

revision = "7d8e9f0a1b2c"
down_revision = "6c7d8e9f0a1b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("application_ai_selections",
        sa.Column("application_id", sa.Integer(), sa.ForeignKey("applications.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("kind", sa.String(80), primary_key=True),
        sa.Column("result_id", sa.Integer(), sa.ForeignKey("application_ai_results.id", ondelete="CASCADE"), nullable=False))
    op.create_index("ix_application_ai_selections_result_id", "application_ai_selections", ["result_id"])
    # Cache reuse was not recorded historically. Preserve the previous displayed choice.
    op.execute(sa.text("""
        INSERT INTO application_ai_selections (application_id, kind, result_id)
        SELECT application_id, kind, id FROM (
            SELECT application_id, kind, id, ROW_NUMBER() OVER (
                PARTITION BY application_id, kind ORDER BY created_at DESC, id DESC
            ) AS position FROM application_ai_results
        ) WHERE position = 1
    """))


def downgrade() -> None:
    op.drop_table("application_ai_selections")
