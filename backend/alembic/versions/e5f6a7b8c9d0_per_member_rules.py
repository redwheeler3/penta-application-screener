"""per-member eligibility rules: member_rules table + committee-default rules row (M15 1d)

M15 1d makes the deterministic hard-filter THRESHOLDS per-member (income/age/children +
disabled rules), mirroring how 1c made the eligibility verdict per-member. The numeric rules
were shared, stored inside the ``app_settings`` AdminSetting blob and re-evaluated at import
into a now-removed ``applications.hard_filter_reasons`` column. This migration splits them out:

  - the committee-default rules move into their OWN AdminSetting row (key
    ``committee_default_rules``), seeded from whatever thresholds the current ``app_settings``
    blob holds — the shared baseline every member reads until they diverge;
  - ``member_rules`` — a sparse per-member table, one row ONLY once a member customizes their
    thresholds (copy-on-write). Starts empty: today's sole member reads the default (which is
    exactly the old global rules), so there is nothing to backfill;
  - the moved rule keys are stripped from the ``app_settings`` blob, which keeps only the
    shared infra config (google_sheet_id, max_dogs, max_cats, allow_other_pets, ai);
  - ``applications.hard_filter_reasons`` is DROPPED. Reasons are no longer stored — they are
    computed on read from each member's rules over ``applications.normalized`` (see
    ``services/rules`` + ``services/eligibility``).

Reversible: downgrade re-adds ``hard_filter_reasons`` (JSON, default ``[]`` — reasons are
recomputed on read, not restored here), merges the committee-default thresholds back into the
``app_settings`` blob, deletes the ``committee_default_rules`` row, and drops ``member_rules``.
LOSSY for N diverged members (their per-member thresholds are discarded on downgrade — only the
committee default survives back into the shared blob). At the single-member / no-divergence
stage today it round-trips exactly. Back up the .db before running.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-07-24
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: str | None = "d4e5f6a7b8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The threshold defaults, duplicated here so the migration never imports app code (which may
# drift from the schema this migration was written against). These match the DEFAULT_*
# constants in app.domain.hard_filters / EligibilityRules at the time of writing.
_DEFAULT_RULES = {
    "income_min": 70000,
    "income_max": 150000,
    "min_adult_age": 18,
    "max_child_age": 17,
    "min_children": 1,
    "max_children": 4,
    "disabled_rules": [],
}
_RULE_KEYS = tuple(_DEFAULT_RULES.keys())


def _load_app_settings(conn) -> tuple[dict, bool]:
    """The stored app_settings blob and whether a row exists."""
    row = conn.execute(
        sa.text("SELECT value FROM admin_settings WHERE key = 'app_settings'")
    ).scalar()
    if row is None:
        return {}, False
    return (json.loads(row) if isinstance(row, str) else dict(row)), True


def upgrade() -> None:
    conn = op.get_bind()

    # 1. The sparse per-member rules table.
    op.create_table(
        "member_rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("rules", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_index(
        op.f("ix_member_rules_user_id"), "member_rules", ["user_id"], unique=True
    )

    # 2. Seed the committee-default rules row from the CURRENT global thresholds in the
    #    app_settings blob (missing keys fall back to the schema defaults). If there is no
    #    app_settings row at all, seed pure defaults.
    stored, _ = _load_app_settings(conn)
    default_rules = {key: stored.get(key, _DEFAULT_RULES[key]) for key in _RULE_KEYS}
    conn.execute(
        sa.text(
            "INSERT INTO admin_settings (key, value, created_at, updated_at) "
            "VALUES ('committee_default_rules', :value, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ),
        {"value": json.dumps(default_rules)},
    )

    # 3. Strip the moved rule keys from the app_settings blob (leave google_sheet_id,
    #    max_dogs, max_cats, allow_other_pets, ai). member_rules stays empty — the sole
    #    member reads the default (copy-on-write divergence).
    if stored:
        cleaned = {k: v for k, v in stored.items() if k not in _RULE_KEYS}
        conn.execute(
            sa.text("UPDATE admin_settings SET value = :value WHERE key = 'app_settings'"),
            {"value": json.dumps(cleaned)},
        )

    # 4. Drop the now-removed stored reasons column (SQLite rebuilds the table in batch mode).
    #    Reasons are computed on read per member now.
    with op.batch_alter_table("applications") as batch:
        batch.drop_column("hard_filter_reasons")


def downgrade() -> None:
    conn = op.get_bind()

    # Re-add hard_filter_reasons (default empty list — reasons are recomputed on read, not
    # restored). server_default so existing rows get a valid JSON value.
    with op.batch_alter_table("applications") as batch:
        batch.add_column(
            sa.Column(
                "hard_filter_reasons", sa.JSON(), nullable=False,
                server_default=sa.text("'[]'"),
            )
        )

    # Merge the committee-default thresholds back into the app_settings blob so the pre-1d
    # shared shape is restored. (Per-member divergence in member_rules is discarded — lossy.)
    default_row = conn.execute(
        sa.text("SELECT value FROM admin_settings WHERE key = 'committee_default_rules'")
    ).scalar()
    default_rules = (
        (json.loads(default_row) if isinstance(default_row, str) else dict(default_row))
        if default_row is not None
        else dict(_DEFAULT_RULES)
    )
    stored, has_row = _load_app_settings(conn)
    if has_row:
        merged = {**stored, **{key: default_rules.get(key, _DEFAULT_RULES[key]) for key in _RULE_KEYS}}
        conn.execute(
            sa.text("UPDATE admin_settings SET value = :value WHERE key = 'app_settings'"),
            {"value": json.dumps(merged)},
        )

    conn.execute(sa.text("DELETE FROM admin_settings WHERE key = 'committee_default_rules'"))

    op.drop_index(op.f("ix_member_rules_user_id"), table_name="member_rules")
    op.drop_table("member_rules")
