"""Prevent deleted IDs from naming a different record; detach expired comparisons.

Revision ID: c83d5f917a2b
Revises: 9f0a1b2c3d4e
"""

import sqlalchemy as sa

from alembic import op

revision = "c83d5f917a2b"
down_revision = "9f0a1b2c3d4e"
branch_labels = None
depends_on = None

IDENTITY_TABLES = (
    "access_allowlist", "admin_settings", "applications", "daily_maintenance_runs",
    "denied_sign_in_attempts", "dimension_aliases", "eval_runs", "retention_deletions",
    "users", "vacancy_subscriptions", "applicant_drafts", "application_ai_results",
    "application_committee_notes", "application_notes", "application_stars",
    "application_versions", "feedback", "openings", "run_lock", "analyses",
    "application_participations", "application_shortlist", "browser_sessions",
    "member_eligibility", "member_rules", "opening_rules", "run_cost_ledger",
    "analysis_audit", "magic_link_tokens", "member_rankings", "run_pass_cost", "email_deliveries",
)
# Skip the legacy allocation range, whose deleted high-water marks were not kept.
# This remains an exact JavaScript integer and leaves ample room below 2**53 - 1.
LEGACY_ID_FLOOR = 2**52
FK_NAME = "fk_browser_sessions_reconciliation_draft_id"
NAMING = {"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}


def _require_safe_rebuild() -> None:
    if op.get_bind().exec_driver_sql("PRAGMA foreign_keys").scalar():
        raise RuntimeError("SQLite table rebuilds require foreign_keys=OFF on the migration connection to preserve child records.")


def _comparison_foreign_key(ondelete: str, *, autoincrement: bool) -> None:
    with op.batch_alter_table("browser_sessions", naming_convention=NAMING,
        table_kwargs={"sqlite_autoincrement": autoincrement}) as batch:
        batch.drop_constraint(FK_NAME, type_="foreignkey")
        batch.create_foreign_key(FK_NAME, "applicant_drafts", ["reconciliation_draft_id"], ["id"], ondelete=ondelete)


def upgrade() -> None:
    _require_safe_rebuild()
    connection = op.get_bind()
    for table in IDENTITY_TABLES:
        if table == "browser_sessions":
            _comparison_foreign_key("SET NULL", autoincrement=True)
        else:
            with op.batch_alter_table(table, recreate="always", table_kwargs={"sqlite_autoincrement": True}):
                pass
        highest = connection.exec_driver_sql(f"SELECT COALESCE(MAX(id), 0) FROM {table}").scalar()
        sequence = max(LEGACY_ID_FLOOR, highest)
        updated = connection.execute(sa.text("UPDATE sqlite_sequence SET seq = :seq WHERE name = :name"),
            {"seq": sequence, "name": table})
        if updated.rowcount == 0:
            connection.execute(sa.text("INSERT INTO sqlite_sequence (name, seq) VALUES (:name, :seq)"),
                {"seq": sequence, "name": table})
    if connection.exec_driver_sql("PRAGMA foreign_key_check").first() is not None:
        raise RuntimeError("Record-identity migration left an invalid foreign key.")


def downgrade() -> None:
    _require_safe_rebuild()
    for table in IDENTITY_TABLES:
        if table == "browser_sessions":
            _comparison_foreign_key("CASCADE", autoincrement=False)
        else:
            with op.batch_alter_table(table, recreate="always", table_kwargs={"sqlite_autoincrement": False}):
                pass
