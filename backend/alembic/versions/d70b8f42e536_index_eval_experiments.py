"""Index existing experiment identity without duplicating eval results.

Revision ID: d70b8f42e536
Revises: c69a7e31d425
"""
from alembic import op

revision = "d70b8f42e536"
down_revision = "c69a7e31d425"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE INDEX ix_eval_runs_experiment ON eval_runs (
            eval_key, coalesce(prompt_version, ''),
            coalesce(json_extract(result, '$.experimentId'), ''), created_at DESC, id DESC
        ) WHERE json_valid(result)
    """)


def downgrade() -> None:
    op.drop_index("ix_eval_runs_experiment", table_name="eval_runs")
