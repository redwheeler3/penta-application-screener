"""remove empty score-current passes

Revision ID: e5a1b2c3d4e5
Revises: d4e9f1a2b3c4
Create Date: 2026-07-14 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e5a1b2c3d4e5"
down_revision: str | None = "d4e9f1a2b3c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            DELETE FROM run_pass_cost
            WHERE run_id IN (
                SELECT id FROM run_cost_ledger WHERE kind = 'rank_scores'
            )
              AND label != 'Dimension scoring'
              AND calls = 0
              AND input_tokens = 0
              AND output_tokens = 0
              AND cost_usd = 0
              AND cached_count = 0
              AND cached_saved_usd = 0
              AND duration_ms = 0
              AND failed_calls = 0
            """
        )
    )


def downgrade() -> None:
    pass
