"""share AI cache identity across equivalent provider routes

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
"""

from __future__ import annotations

import hashlib
import json

import sqlalchemy as sa
from sqlalchemy.engine import Connection, RowMapping
from sqlalchemy.orm import Session

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

# Frozen prompt identities at this migration. They let a currently valid Rank stay
# current while genuinely stale fingerprints remain untouched.
_PROMPT_VERSIONS = {
    "discovery": "87415213bc2b",
    "decompose": "196def77f77b",
    "match": "2a463a1f6443",
    "scoring": "d05026e73450",
    "consolidate": "d73b755d3075",
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


def _rank_fingerprint(db: Session, ai: object, *, canonical: bool) -> str:
    from app.services.analysis_freshness import pool_fingerprint

    def identity(model_id: str) -> str:
        return _ROUTE_TO_MODEL_IDENTITY[model_id] if canonical else model_id

    parts = [
        pool_fingerprint(db),
        *[f"{name}:{version}" for name, version in _PROMPT_VERSIONS.items()],
        f"discovery_model:{identity(ai.discovery_model)}",
        f"decompose_model:{identity(ai.decompose_model)}",
        f"match_model:{identity(ai.match_model)}",
        f"scoring_model:{identity(ai.dimension_scoring_model)}",
        f"consolidate_model:{identity(ai.consolidate_model)}",
    ]
    reasoning_settings = (
        ("discovery", ai.discovery_model, ai.discovery_reasoning_effort),
        ("decompose", ai.decompose_model, ai.decompose_reasoning_effort),
        ("match", ai.match_model, ai.match_reasoning_effort),
        ("scoring", ai.dimension_scoring_model, ai.dimension_scoring_reasoning_effort),
        ("consolidate", ai.consolidate_model, ai.consolidate_reasoning_effort),
    )
    for pass_name, model_id, effort in reasoning_settings:
        if model_id.startswith("openai.") or model_id.startswith("gpt-"):
            parts.append(f"{pass_name}_reasoning:{effort}")
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:16]


def _rekey_current_rank(connection: Connection, *, canonical: bool) -> None:
    from app.schemas.settings import AppSettings
    from app.services.settings import APP_SETTINGS_KEY

    value = connection.scalar(
        sa.text("SELECT value FROM admin_settings WHERE key = :key"),
        {"key": APP_SETTINGS_KEY},
    )
    if value is None:
        return
    settings = (
        AppSettings.model_validate_json(value)
        if isinstance(value, str)
        else AppSettings.model_validate(value)
    )
    db = Session(bind=connection)
    source = _rank_fingerprint(db, settings.ai, canonical=not canonical)
    target = _rank_fingerprint(db, settings.ai, canonical=canonical)
    connection.execute(
        sa.text(
            "UPDATE analyses SET rank_inputs_fingerprint = :target "
            "WHERE rank_inputs_fingerprint = :source"
        ),
        {"source": source, "target": target},
    )


def upgrade() -> None:
    connection = op.get_bind()
    _rekey_results(connection, canonical=True)
    _rekey_current_rank(connection, canonical=True)


def downgrade() -> None:
    connection = op.get_bind()
    _rekey_current_rank(connection, canonical=False)
    _rekey_results(connection, canonical=False)
