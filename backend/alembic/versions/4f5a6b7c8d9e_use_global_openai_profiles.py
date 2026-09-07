"""use global OpenAI inference profiles

Revision ID: 4f5a6b7c8d9e
Revises: 3e4f5a6b7c8d
Create Date: 2026-09-06
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "4f5a6b7c8d9e"
down_revision: str | None = "3e4f5a6b7c8d"
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
_MANTLE_TO_GLOBAL = {
    "openai.gpt-5.6-luna": "global.openai.gpt-5.6-luna",
    "openai.gpt-5.6-terra": "global.openai.gpt-5.6-terra",
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


def _replace_route_ids(settings: dict, replacements: Mapping[str, str]) -> bool:
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
    if settings is not None and _replace_route_ids(settings, replacements):
        _save_settings(connection, settings)


def upgrade() -> None:
    # Only active settings move transports. Historical results, ledgers, and eval
    # fixtures keep the exact Mantle model ID that produced their output.
    _migrate(_MANTLE_TO_GLOBAL)


def downgrade() -> None:
    _migrate({global_id: mantle_id for mantle_id, global_id in _MANTLE_TO_GLOBAL.items()})
