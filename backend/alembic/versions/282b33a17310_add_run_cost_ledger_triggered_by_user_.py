"""add run_cost_ledger.triggered_by_user_id (M15 Phase 4)

Additive: a nullable ``triggered_by_user_id`` FK on ``run_cost_ledger`` stamping the member
who kicked off each shared run (Screen / Rank / score-current), so Observability can attribute
the shared spend (M15 Phase 4; ADR 0011). Observability stays committee-wide — this is
attribution, not per-member scoping.

Nullable, no backfill: pre-Phase-4 rows stay NULL and simply render without a stamp. The FK is
plain (no ``ON DELETE CASCADE``): a run's cost history must OUTLIVE a removed member — the row
survives, the stamp just reads blank (the relationship resolves to None). Uses
``batch_alter_table`` because SQLite can't add a column with an FK constraint in place. Named
constraint (``fk_run_cost_ledger_triggered_by_user_id``) so the downgrade can drop it by name.
Back up the .db before running.

Revision ID: 282b33a17310
Revises: 725bae661bc1
Create Date: 2026-07-24 20:26:25.612632
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "282b33a17310"
down_revision: str | None = "725bae661bc1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FK = "fk_run_cost_ledger_triggered_by_user_id"
_IX = "ix_run_cost_ledger_triggered_by_user_id"


def upgrade() -> None:
    with op.batch_alter_table("run_cost_ledger") as batch:
        batch.add_column(sa.Column("triggered_by_user_id", sa.Integer(), nullable=True))
        batch.create_index(_IX, ["triggered_by_user_id"], unique=False)
        batch.create_foreign_key(_FK, "users", ["triggered_by_user_id"], ["id"])


def downgrade() -> None:
    with op.batch_alter_table("run_cost_ledger") as batch:
        batch.drop_constraint(_FK, type_="foreignkey")
        batch.drop_index(_IX)
        batch.drop_column("triggered_by_user_id")
