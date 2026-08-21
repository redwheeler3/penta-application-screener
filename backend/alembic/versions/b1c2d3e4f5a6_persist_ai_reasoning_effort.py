"""persist per-pass AI reasoning effort in app settings

Revision ID: b1c2d3e4f5a6
Revises: a0b1c2d3e4f5
"""

from __future__ import annotations

import json

import sqlalchemy as sa

from alembic import op

revision = "b1c2d3e4f5a6"
down_revision = "a0b1c2d3e4f5"
branch_labels = None
depends_on = None

_KEYS = (
    "screening_reasoning_effort",
    "dimension_scoring_reasoning_effort",
    "discovery_reasoning_effort",
    "decompose_reasoning_effort",
    "match_reasoning_effort",
    "consolidate_reasoning_effort",
)


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


def upgrade() -> None:
    connection = op.get_bind()
    settings = _load_settings(connection)
    if settings is None:
        return
    ai = dict(settings.get("ai") or {})
    for key in _KEYS:
        ai.setdefault(key, "low")
    settings["ai"] = ai
    _save_settings(connection, settings)


def downgrade() -> None:
    connection = op.get_bind()
    settings = _load_settings(connection)
    if settings is None:
        return
    ai = dict(settings.get("ai") or {})
    for key in _KEYS:
        ai.pop(key, None)
    settings["ai"] = ai
    _save_settings(connection, settings)
