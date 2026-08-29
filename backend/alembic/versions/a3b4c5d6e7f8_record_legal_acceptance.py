"""record legal acceptance and name application withdrawal truthfully

Revision ID: a3b4c5d6e7f8
Revises: 9d0e1f2a3b4c
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a3b4c5d6e7f8"
down_revision: str | None = "9d0e1f2a3b4c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(sa.text("DROP TABLE IF EXISTS _alembic_tmp_applications"))
    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("applications")}
    if "uq_applications_active_primary_email" in indexes:
        op.drop_index("uq_applications_active_primary_email", table_name="applications")
    if "ix_applications_deleted_at" in indexes:
        op.drop_index("ix_applications_deleted_at", table_name="applications")
    op.alter_column("applications", "deleted_at", new_column_name="withdrawn_at")
    op.create_index(
        "ix_applications_withdrawn_at",
        "applications",
        ["withdrawn_at"],
    )
    op.create_index(
        "uq_applications_active_primary_email",
        "applications",
        ["primary_email"],
        unique=True,
        sqlite_where=sa.text("withdrawn_at IS NULL"),
        postgresql_where=sa.text("withdrawn_at IS NULL"),
    )
    with op.batch_alter_table("application_versions") as batch:
        batch.add_column(sa.Column("terms_version", sa.String(length=30), nullable=True))
    with op.batch_alter_table("vacancy_subscriptions") as batch:
        batch.add_column(sa.Column("consent_version", sa.String(length=30), nullable=True))
    op.create_table(
        "vacancy_consent_receipts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("subscription_id", sa.Integer(), nullable=False),
        sa.Column("email_hash", sa.String(length=64), nullable=False),
        sa.Column("unit_sizes", sa.JSON(), nullable=False),
        sa.Column("consented_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consent_version", sa.String(length=30), nullable=True),
        sa.Column("source", sa.String(length=120), nullable=False),
        sa.Column("fulfilled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retain_until", sa.Date(), nullable=False),
        sa.Column("email_delivery_id", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_vacancy_consent_receipts_email_hash",
        "vacancy_consent_receipts",
        ["email_hash"],
    )
    op.create_index(
        "ix_vacancy_consent_receipts_retain_until",
        "vacancy_consent_receipts",
        ["retain_until"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_vacancy_consent_receipts_retain_until",
        table_name="vacancy_consent_receipts",
    )
    op.drop_index(
        "ix_vacancy_consent_receipts_email_hash",
        table_name="vacancy_consent_receipts",
    )
    op.drop_table("vacancy_consent_receipts")
    with op.batch_alter_table("vacancy_subscriptions") as batch:
        batch.drop_column("consent_version")
    with op.batch_alter_table("application_versions") as batch:
        batch.drop_column("terms_version")
    op.drop_index("uq_applications_active_primary_email", table_name="applications")
    op.drop_index("ix_applications_withdrawn_at", table_name="applications")
    op.alter_column("applications", "withdrawn_at", new_column_name="deleted_at")
    op.create_index("ix_applications_deleted_at", "applications", ["deleted_at"])
    op.create_index(
        "uq_applications_active_primary_email",
        "applications",
        ["primary_email"],
        unique=True,
        sqlite_where=sa.text("deleted_at IS NULL"),
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
