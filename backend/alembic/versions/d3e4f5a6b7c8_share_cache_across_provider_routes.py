"""share AI cache identity across equivalent provider routes

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
"""

from __future__ import annotations

import hashlib
import json

import sqlalchemy as sa
from sqlalchemy.engine import Connection, RowMapping

from alembic import op

revision = "d3e4f5a6b7c8"
down_revision = "c2d3e4f5a6b7"
branch_labels = None
depends_on = None

_ROUTE_TO_MODEL_IDENTITY = {
    "us.anthropic.claude-haiku-4-5-20251001-v1:0": "anthropic:claude-haiku-4-5-20251001",
    "claude-haiku-4-5-20251001": "anthropic:claude-haiku-4-5-20251001",
    "us.anthropic.claude-sonnet-4-6": "anthropic:claude-sonnet-4-6",
    "claude-sonnet-4-6": "anthropic:claude-sonnet-4-6",
    "openai.gpt-5.6-luna": "openai:gpt-5.6-luna",
    "gpt-5.6-luna": "openai:gpt-5.6-luna",
    "openai.gpt-5.6-terra": "openai:gpt-5.6-terra",
    "gpt-5.6-terra": "openai:gpt-5.6-terra",
}

def _cache_key(row: RowMapping, model_identity: str) -> str:
    identity = {
        "raw_hash": row["raw_row_hash"],
        "kind": row["kind"],
        "model_id": model_identity,
        "prompt_version": row["prompt_version"],
    }
    if row["reasoning_effort"] is not None:
        identity["reasoning_effort"] = row["reasoning_effort"]
    basis = json.dumps(identity, sort_keys=True)
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def _rekey_results(connection: Connection, *, canonical: bool) -> None:
    rows = connection.execute(
        sa.text(
            "SELECT r.id, r.cache_key, r.kind, r.model_id, r.prompt_version, "
            "r.reasoning_effort, a.raw_row_hash FROM application_ai_results r "
            "JOIN applications a ON a.id = r.application_id"
        )
    ).mappings()
    for row in rows:
        shared_identity = _ROUTE_TO_MODEL_IDENTITY.get(row["model_id"])
        if shared_identity is None:
            continue
        source_identity = row["model_id"] if canonical else shared_identity
        if row["cache_key"] != _cache_key(row, source_identity):
            continue
        target_identity = shared_identity if canonical else row["model_id"]
        target_key = _cache_key(row, target_identity)
        occupied = connection.scalar(
            sa.text(
                "SELECT 1 FROM application_ai_results "
                "WHERE cache_key = :cache_key AND id != :result_id"
            ),
            {"cache_key": target_key, "result_id": row["id"]},
        )
        # Both routes may already have a result. Keep both provenance rows and let the
        # row already holding the canonical key serve future cache hits.
        if occupied is None:
            connection.execute(
                sa.text(
                    "UPDATE application_ai_results SET cache_key = :cache_key "
                    "WHERE id = :result_id"
                ),
                {"cache_key": target_key, "result_id": row["id"]},
            )


def upgrade() -> None:
    connection = op.get_bind()
    _rekey_results(connection, canonical=True)


def downgrade() -> None:
    connection = op.get_bind()
    _rekey_results(connection, canonical=False)
