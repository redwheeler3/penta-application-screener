"""rename disabled_rules -> disabled_checks in stored rules blobs (M15 1g Move 3)

1g Move 2 lets a member switch off AI screening checks (flag categories) the same way they
already switch off deterministic rules — via one flat set. Once that set spans both kinds,
``disabled_rules`` mildly lies (a flag category isn't a "rule"), so the field is renamed to
``disabled_checks`` across ``EligibilityRules`` / ``RulesConfig``. The stored JSON blobs carry
the old key and must be rewritten:

  - the committee-default rules row (``AdminSetting`` key ``committee_default_rules``);
  - every ``member_rules`` row (sparse — only diverged members have one).

Pure key rename inside the JSON value (``disabled_rules`` -> ``disabled_checks``), values
preserved. No schema/DDL change. Reversible: downgrade renames the key back. Absent key or
absent rows are fine (nothing to rewrite). Back up the .db before running.

Revision ID: b8c9d0e1f2a3
Revises: f6a7b8c9d0e1
Create Date: 2026-07-24
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b8c9d0e1f2a3"
down_revision: str | None = "f6a7b8c9d0e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _rename_key(blob: dict, old: str, new: str) -> dict:
    """Return blob with key ``old`` renamed to ``new`` (no-op if ``old`` absent). If ``new``
    somehow already exists it wins (we don't clobber it)."""
    if old in blob and new not in blob:
        blob[new] = blob.pop(old)
    else:
        blob.pop(old, None)
    return blob


def _migrate(conn, old: str, new: str) -> None:
    # committee_default_rules (single AdminSetting row)
    row = conn.execute(
        sa.text("SELECT value FROM admin_settings WHERE key = 'committee_default_rules'")
    ).scalar()
    if row is not None:
        blob = json.loads(row) if isinstance(row, str) else dict(row)
        conn.execute(
            sa.text("UPDATE admin_settings SET value = :v WHERE key = 'committee_default_rules'"),
            {"v": json.dumps(_rename_key(blob, old, new))},
        )

    # member_rules (sparse per-member rows)
    for row_id, value in conn.execute(sa.text("SELECT id, rules FROM member_rules")).all():
        blob = json.loads(value) if isinstance(value, str) else dict(value)
        conn.execute(
            sa.text("UPDATE member_rules SET rules = :v WHERE id = :id"),
            {"v": json.dumps(_rename_key(blob, old, new)), "id": row_id},
        )


def upgrade() -> None:
    _migrate(op.get_bind(), "disabled_rules", "disabled_checks")


def downgrade() -> None:
    _migrate(op.get_bind(), "disabled_checks", "disabled_rules")
