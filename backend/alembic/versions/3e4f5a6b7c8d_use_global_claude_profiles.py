"""use global Claude inference profiles

Revision ID: 3e4f5a6b7c8d
Revises: 2d3e4f5a6b7c
Create Date: 2026-09-06
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "3e4f5a6b7c8d"
down_revision: str | None = "2d3e4f5a6b7c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MODEL_KEYS = (
    "screening_model",
    "dimension_scoring_model",
    "discovery_model",
    "decompose_model",
    "match_model",
    "consolidate_model",
)
_US_TO_GLOBAL = {
    "us.anthropic.claude-haiku-4-5-20251001-v1:0": (
        "global.anthropic.claude-haiku-4-5-20251001-v1:0"
    ),
    "us.anthropic.claude-sonnet-4-6": "global.anthropic.claude-sonnet-4-6",
}


def _load_settings(connection) -> dict | None:
    value = connection.scalar(
        sa.text("SELECT value FROM admin_settings WHERE key = 'app_settings'")
    )
    if value is None:
        return None
    return json.loads(value) if isinstance(value, str) else dict(value)


def _save_settings(connection, settings: dict) -> None:
    connection.execute(
        sa.text(
            "UPDATE admin_settings SET value = :value, updated_at = CURRENT_TIMESTAMP "
            "WHERE key = 'app_settings'"
        ),
        {"value": json.dumps(settings)},
    )


def _replace_profile_ids(settings: dict, replacements: Mapping[str, str]) -> bool:
    ai = dict(settings.get("ai") or {})
    changed = False
    for key in _MODEL_KEYS:
        current = ai.get(key)
        if replacement := replacements.get(current):
            ai[key] = replacement
            changed = True
    if changed:
        settings["ai"] = ai
    return changed


def _migrate(replacements: Mapping[str, str]) -> None:
    connection = op.get_bind()
    settings = _load_settings(connection)
    if settings is not None and _replace_profile_ids(settings, replacements):
        _save_settings(connection, settings)


def upgrade() -> None:
    # Settings select the invocation route. Historical result and cost rows retain the
    # exact US route that produced them; their provider-neutral cache identity already
    # lets the equivalent global route reuse valid work.
    _migrate(_US_TO_GLOBAL)


def downgrade() -> None:
    _migrate({global_id: us_id for us_id, global_id in _US_TO_GLOBAL.items()})
