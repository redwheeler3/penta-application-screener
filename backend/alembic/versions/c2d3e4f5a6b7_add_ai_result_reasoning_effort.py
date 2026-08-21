"""store reasoning effort on cached AI results

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
"""

from __future__ import annotations

import hashlib
import json

import sqlalchemy as sa
from sqlalchemy.engine import RowMapping

from alembic import op

revision = "c2d3e4f5a6b7"
down_revision = "b1c2d3e4f5a6"
branch_labels = None
depends_on = None

_REASONING_EFFORTS = ("none", "low", "medium", "high", "xhigh", "max")


def _cache_key(row: RowMapping, reasoning_effort: str) -> str:
    identity = {
        "raw_hash": row["raw_row_hash"],
        "kind": row["kind"],
        "model_id": row["model_id"],
        "prompt_version": row["prompt_version"],
        "reasoning_effort": reasoning_effort,
    }
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()


def upgrade() -> None:
    op.add_column(
        "application_ai_results",
        sa.Column("reasoning_effort", sa.String(length=10), nullable=True),
    )
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT r.id, r.cache_key, r.kind, r.model_id, r.prompt_version, "
            "a.raw_row_hash FROM application_ai_results r "
            "JOIN applications a ON a.id = r.application_id "
            "WHERE r.model_id LIKE 'openai.%'"
        )
    ).mappings()
    for row in rows:
        effort = next(
            (
                candidate
                for candidate in _REASONING_EFFORTS
                if _cache_key(row, candidate) == row["cache_key"]
            ),
            None,
        )
        if effort is not None:
            connection.execute(
                sa.text(
                    "UPDATE application_ai_results SET reasoning_effort = :effort "
                    "WHERE id = :result_id"
                ),
                {"effort": effort, "result_id": row["id"]},
            )


def downgrade() -> None:
    op.drop_column("application_ai_results", "reasoning_effort")
