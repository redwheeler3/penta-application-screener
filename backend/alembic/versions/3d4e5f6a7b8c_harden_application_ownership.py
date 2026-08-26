"""harden application ownership

Revision ID: 3d4e5f6a7b8c
Revises: 2c3d4e5f6a7b
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "3d4e5f6a7b8c"
down_revision: str | None = "2c3d4e5f6a7b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NAMING_CONVENTION = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"
}

_OWNED_FOREIGN_KEYS = (
    ("application_participations", "application_id", "applications"),
    ("application_versions", "application_id", "applications"),
    ("applicant_drafts", "application_id", "applications"),
    ("magic_link_tokens", "application_id", "applications"),
    ("magic_link_tokens", "applicant_draft_id", "applicant_drafts"),
    ("browser_sessions", "application_id", "applications"),
    ("email_deliveries", "application_id", "applications"),
    ("email_deliveries", "magic_link_token_id", "magic_link_tokens"),
    ("email_deliveries", "applicant_draft_id", "applicant_drafts"),
    ("member_eligibility", "application_id", "applications"),
    ("application_notes", "application_id", "applications"),
    ("application_stars", "application_id", "applications"),
    ("application_ai_results", "application_id", "applications"),
)


def _foreign_key_name(table: str, column: str, referred_table: str) -> str:
    return f"fk_{table}_{column}_{referred_table}"


def _replace_owned_foreign_keys(*, ondelete: str | None) -> None:
    tables = dict.fromkeys(table for table, _, _ in _OWNED_FOREIGN_KEYS)
    for table in tables:
        # SQLite batch mode uses this deterministic scratch table. Removing a leftover
        # empty artifact makes the migration safely restartable after an interrupted rebuild.
        op.execute(sa.text(f"DROP TABLE IF EXISTS _alembic_tmp_{table}"))
        existing_foreign_keys = sa.inspect(op.get_bind()).get_foreign_keys(table)
        changes = []
        for _, column, referred_table in (
            item for item in _OWNED_FOREIGN_KEYS if item[0] == table
        ):
            existing = next(
                (
                    foreign_key
                    for foreign_key in existing_foreign_keys
                    if foreign_key["constrained_columns"] == [column]
                    and foreign_key["referred_table"] == referred_table
                ),
                None,
            )
            existing_ondelete = (
                str(existing.get("options", {}).get("ondelete", "")).upper()
                if existing is not None
                else None
            )
            desired_ondelete = ondelete.upper() if ondelete is not None else ""
            if existing is not None and existing_ondelete == desired_ondelete:
                continue
            changes.append((column, referred_table, existing))
        if not changes:
            continue
        with op.batch_alter_table(
            table,
            naming_convention=_NAMING_CONVENTION,
        ) as batch:
            for column, referred_table, existing in changes:
                name = _foreign_key_name(table, column, referred_table)
                if existing is not None:
                    batch.drop_constraint(existing["name"] or name, type_="foreignkey")
                batch.create_foreign_key(
                    name,
                    referred_table,
                    [column],
                    ["id"],
                    ondelete=ondelete,
                )


def upgrade() -> None:
    _replace_owned_foreign_keys(ondelete="CASCADE")
    op.create_table(
        "daily_maintenance_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task", sa.String(length=80), nullable=False),
        sa.Column("pacific_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("last_error_code", sa.String(length=120)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task", "pacific_date"),
    )
    for column in ("task", "pacific_date", "status"):
        op.create_index(
            f"ix_daily_maintenance_runs_{column}",
            "daily_maintenance_runs",
            [column],
        )

    op.create_table(
        "retention_deletions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("record_kind", sa.String(length=30), nullable=False),
        sa.Column("record_id", sa.Integer(), nullable=False),
        sa.Column("retention_rule", sa.String(length=50), nullable=False),
        sa.Column("due_on", sa.Date(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("record_kind", "record_id"),
    )


def downgrade() -> None:
    op.drop_table("retention_deletions")
    for column in reversed(("task", "pacific_date", "status")):
        op.drop_index(
            f"ix_daily_maintenance_runs_{column}",
            table_name="daily_maintenance_runs",
        )
    op.drop_table("daily_maintenance_runs")
    _replace_owned_foreign_keys(ondelete=None)
