"""remove Google Sheet intake

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
"""

from collections.abc import Callable, Sequence
from typing import Any

import sqlalchemy as sa

from alembic import op

revision: str = "d5e6f7a8b9c0"
down_revision: str | None = "c4d5e6f7a8b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LEGACY_SYNTHETIC_SHEET_ID = "1shuJeJRWL05F4TCQ9yr0-uiQB58MbjaNc6dkokmBn8Y"


def _update_app_settings(
    connection: sa.Connection,
    transform: Callable[[dict[str, Any]], dict[str, Any]],
) -> None:
    admin_settings = sa.table(
        "admin_settings",
        sa.column("key", sa.String()),
        sa.column("value", sa.JSON()),
    )
    value = connection.execute(
        sa.select(admin_settings.c.value).where(admin_settings.c.key == "app_settings")
    ).scalar_one_or_none()
    if not isinstance(value, dict):
        return
    updated: dict[str, Any] = transform(dict(value))
    connection.execute(
        sa.update(admin_settings)
        .where(admin_settings.c.key == "app_settings")
        .values(value=updated)
    )


def _without_sheet_settings(value: dict[str, Any]) -> dict[str, Any]:
    value.pop("google_sheet_id", None)
    value.pop("google_sheet_reader_user_id", None)
    return value


def _with_empty_sheet_settings(value: dict[str, Any]) -> dict[str, Any]:
    value.setdefault("google_sheet_id", "")
    value.setdefault("google_sheet_reader_user_id", None)
    return value


def upgrade() -> None:
    connection = op.get_bind()
    with op.batch_alter_table("applications") as batch:
        batch.add_column(
            sa.Column(
                "synthetic_data",
                sa.Boolean(),
                server_default=sa.false(),
                nullable=False,
            )
        )
    with op.batch_alter_table("analyses") as batch:
        batch.add_column(
            sa.Column(
                "synthetic_data",
                sa.Boolean(),
                server_default=sa.false(),
                nullable=False,
            )
        )

    # Preserve the one existing provenance fact needed for safe fixture export before
    # removing the source-specific tables. Every unknown source remains fail-closed.
    connection.execute(
        sa.text(
            "UPDATE applications SET synthetic_data = 1 WHERE EXISTS "
            "(SELECT 1 FROM sync_runs WHERE source_sheet_id = :sheet_id)"
        ).bindparams(sheet_id=_LEGACY_SYNTHETIC_SHEET_ID)
    )
    connection.execute(
        sa.text(
            "UPDATE analyses SET synthetic_data = 1 WHERE source_sync_run_id IN "
            "(SELECT id FROM sync_runs WHERE source_sheet_id = :sheet_id)"
        ).bindparams(sheet_id=_LEGACY_SYNTHETIC_SHEET_ID)
    )

    with op.batch_alter_table("analyses") as batch:
        batch.drop_column("source_sync_run_id")
    _update_app_settings(connection, _without_sheet_settings)
    op.drop_table("google_credentials")
    op.drop_table("sync_runs")


def downgrade() -> None:
    connection = op.get_bind()
    op.create_table(
        "sync_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_sheet_id", sa.String(length=255), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duplicate_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("imported_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unchanged_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("deleted_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("settings_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "google_credentials",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), unique=True, nullable=False),
        sa.Column("token", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    with op.batch_alter_table("analyses") as batch:
        batch.add_column(sa.Column("source_sync_run_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_analyses_source_sync_run_id_sync_runs",
            "sync_runs",
            ["source_sync_run_id"],
            ["id"],
        )
        batch.drop_column("synthetic_data")
    with op.batch_alter_table("applications") as batch:
        batch.drop_column("synthetic_data")
    _update_app_settings(connection, _with_empty_sheet_settings)
