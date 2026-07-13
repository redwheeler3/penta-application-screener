"""split run cost ledger into header + per-pass rows

Revision ID: a1f4c7e29b83
Revises: 8c2b1295e691
Create Date: 2026-07-12 03:30:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = 'a1f4c7e29b83'
down_revision: str | None = '8c2b1295e691'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The ledger becomes a thin header; per-pass cost (now with a token + model
    # breakdown) moves to run_pass_cost, one row per pass. The old JSON blob + rolled-up
    # dollar columns are dropped — no backward-compat during MVP; the DB resets.
    op.drop_column('run_cost_ledger', 'passes')
    op.drop_column('run_cost_ledger', 'fresh_usd')
    op.drop_column('run_cost_ledger', 'cached_saved_usd')

    op.create_table(
        'run_pass_cost',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('run_id', sa.Integer(), nullable=False),
        sa.Column('label', sa.String(length=80), nullable=False),
        sa.Column('model_id', sa.String(length=200), nullable=False, server_default=''),
        sa.Column('calls', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('input_tokens', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('output_tokens', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('cost_usd', sa.Float(), nullable=False, server_default='0'),
        sa.Column('cached_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('cached_saved_usd', sa.Float(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['run_id'], ['run_cost_ledger.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_run_pass_cost_run_id'), 'run_pass_cost', ['run_id'], unique=False)
    op.create_index(op.f('ix_run_pass_cost_label'), 'run_pass_cost', ['label'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_run_pass_cost_label'), table_name='run_pass_cost')
    op.drop_index(op.f('ix_run_pass_cost_run_id'), table_name='run_pass_cost')
    op.drop_table('run_pass_cost')
    op.add_column('run_cost_ledger', sa.Column('cached_saved_usd', sa.Float(), nullable=False, server_default='0'))
    op.add_column('run_cost_ledger', sa.Column('fresh_usd', sa.Float(), nullable=False, server_default='0'))
    op.add_column('run_cost_ledger', sa.Column('passes', sa.JSON(), nullable=False, server_default='[]'))
