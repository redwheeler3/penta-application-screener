"""separate score-current cost runs

Revision ID: d4e9f1a2b3c4
Revises: c3f9a82d1b70
Create Date: 2026-07-14 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d4e9f1a2b3c4"
down_revision: str | None = "c3f9a82d1b70"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE run_cost_ledger
            SET kind = 'rank_scores'
            WHERE kind = 'rank'
              AND EXISTS (
                  SELECT 1
                  FROM run_pass_cost
                  WHERE run_pass_cost.run_id = run_cost_ledger.id
                    AND run_pass_cost.label = 'Dimension scoring'
              )
              AND NOT EXISTS (
                  SELECT 1
                  FROM run_pass_cost
                  WHERE run_pass_cost.run_id = run_cost_ledger.id
                    AND run_pass_cost.label != 'Dimension scoring'
                    AND run_pass_cost.calls > 0
              )
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("UPDATE run_cost_ledger SET kind = 'rank' WHERE kind = 'rank_scores'"))
