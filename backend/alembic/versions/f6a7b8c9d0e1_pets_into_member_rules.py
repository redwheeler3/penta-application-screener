"""move pet limits from the shared app_settings blob into committee_default_rules (M15 1e)

M15 1e makes pet limits per-member, the same way 1d did the numeric thresholds. Pets used to
be judged inside the shared screening PROMPT against limits stored in the ``app_settings`` blob
(``max_dogs`` / ``max_cats`` / ``allow_other_pets``). 1e moves pet judgment to a deterministic
per-member hard filter over AI-extracted pet FACTS, so the limits become eligibility rules and
must live where the other per-member rules live:

  - the three pet keys move OUT of the ``app_settings`` blob and INTO the existing
    ``committee_default_rules`` AdminSetting row (seeded in 1d), so the committee default keeps
    exactly the pet limits it had — every non-diverged member reads them;
  - any ``member_rules`` rows written under 1d predate the pet keys; this migration backfills
    each with the committee-default pet limits, so a member who already diverged on numeric
    rules keeps a complete, coherent ruleset (Model A: a member's rules are a whole set, never
    a sparse patch) rather than silently inheriting live-default pets.

No schema change and nothing touches cached screening results: pre-1e results simply lack a
``pets`` key, which the read path treats as "no facts extracted" (the pet check is skipped for
that app until it is re-screened). A re-screen under the new prompt is what populates pet facts.

Reversible: downgrade merges the pet keys from ``committee_default_rules`` back into the
``app_settings`` blob and strips them from ``committee_default_rules`` + every ``member_rules``
row. LOSSY only in the sense that per-member pet DIVERGENCE (a member whose pet limits differ
from the default) collapses to the default on downgrade — the pre-1e world had no per-member
pet limits, so there is nowhere to put it. At today's stage (pets just moved, no member has
diverged on pets yet) it round-trips exactly. Back up the .db before running.

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-07-24
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f6a7b8c9d0e1"
down_revision: str | None = "e5f6a7b8c9d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The pet defaults, duplicated here so the migration never imports app code (which may drift
# from the schema this migration was written against). These match the DEFAULT_* pet constants
# in app.domain.hard_filters / EligibilityRules at the time of writing.
_DEFAULT_PETS = {
    "max_dogs": 1,
    "max_cats": 1,
    "allow_other_pets": False,
}
_PET_KEYS = tuple(_DEFAULT_PETS.keys())


def _load_json(conn, key: str) -> tuple[dict, bool]:
    """The stored AdminSetting blob for ``key`` and whether a row exists."""
    row = conn.execute(
        sa.text("SELECT value FROM admin_settings WHERE key = :key"), {"key": key}
    ).scalar()
    if row is None:
        return {}, False
    return (json.loads(row) if isinstance(row, str) else dict(row)), True


def upgrade() -> None:
    conn = op.get_bind()

    # The pet limits to carry over: whatever the app_settings blob holds today, else defaults.
    stored, has_settings = _load_json(conn, "app_settings")
    pets = {key: stored.get(key, _DEFAULT_PETS[key]) for key in _PET_KEYS}

    # 1. Merge the pet keys into the committee-default rules row (create it if 1d somehow left
    #    none — seed from pure defaults + these pets).
    default_rules, has_default = _load_json(conn, "committee_default_rules")
    default_rules.update(pets)
    if has_default:
        conn.execute(
            sa.text("UPDATE admin_settings SET value = :value WHERE key = 'committee_default_rules'"),
            {"value": json.dumps(default_rules)},
        )
    else:
        conn.execute(
            sa.text(
                "INSERT INTO admin_settings (key, value, created_at, updated_at) "
                "VALUES ('committee_default_rules', :value, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"value": json.dumps(default_rules)},
        )

    # 2. Backfill every existing member_rules row with the committee-default pet limits, so a
    #    member who diverged under 1d keeps a complete ruleset (Model A). Only fill keys that
    #    are missing — never clobber a value a member somehow already set.
    for row_id, value in conn.execute(
        sa.text("SELECT id, rules FROM member_rules")
    ).all():
        rules = json.loads(value) if isinstance(value, str) else dict(value)
        for key in _PET_KEYS:
            rules.setdefault(key, pets[key])
        conn.execute(
            sa.text("UPDATE member_rules SET rules = :value WHERE id = :id"),
            {"value": json.dumps(rules), "id": row_id},
        )

    # 3. Strip the pet keys from the app_settings blob — it is pure infra now (google_sheet_id,
    #    ai).
    if has_settings:
        cleaned = {k: v for k, v in stored.items() if k not in _PET_KEYS}
        conn.execute(
            sa.text("UPDATE admin_settings SET value = :value WHERE key = 'app_settings'"),
            {"value": json.dumps(cleaned)},
        )


def downgrade() -> None:
    conn = op.get_bind()

    # Pull the pet limits back out of the committee default (else defaults) and merge them into
    # the app_settings blob, restoring the pre-1e shared shape.
    default_rules, _ = _load_json(conn, "committee_default_rules")
    pets = {key: default_rules.get(key, _DEFAULT_PETS[key]) for key in _PET_KEYS}

    stored, has_settings = _load_json(conn, "app_settings")
    if has_settings:
        stored.update(pets)
        conn.execute(
            sa.text("UPDATE admin_settings SET value = :value WHERE key = 'app_settings'"),
            {"value": json.dumps(stored)},
        )
    else:
        conn.execute(
            sa.text(
                "INSERT INTO admin_settings (key, value, created_at, updated_at) "
                "VALUES ('app_settings', :value, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"value": json.dumps(pets)},
        )

    # Strip the pet keys back out of committee_default_rules and every member_rules row.
    if default_rules:
        cleaned = {k: v for k, v in default_rules.items() if k not in _PET_KEYS}
        conn.execute(
            sa.text("UPDATE admin_settings SET value = :value WHERE key = 'committee_default_rules'"),
            {"value": json.dumps(cleaned)},
        )
    for row_id, value in conn.execute(
        sa.text("SELECT id, rules FROM member_rules")
    ).all():
        rules = json.loads(value) if isinstance(value, str) else dict(value)
        cleaned = {k: v for k, v in rules.items() if k not in _PET_KEYS}
        conn.execute(
            sa.text("UPDATE member_rules SET rules = :value WHERE id = :id"),
            {"value": json.dumps(cleaned), "id": row_id},
        )
