"""add M21 intake foundation

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e4f5a6b7c8d9"
down_revision: str | None = "d3e4f5a6b7c8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("applications") as batch:
        batch.add_column(sa.Column("working_answers", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("working_content_hash", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("working_saved_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(
            sa.Column("declaration_accepted_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch.add_column(sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("retention_due_on", sa.Date(), nullable=True))
        batch.create_index("ix_applications_submitted_at", ["submitted_at"])
        batch.create_index("ix_applications_deleted_at", ["deleted_at"])

    # Every pre-M21 row came from a submitted Google Form response. Preserve that
    # historical fact without inventing a separate submission time.
    op.execute("UPDATE applications SET submitted_at = created_at")

    op.create_table(
        "openings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("unit_size_bedrooms", sa.Integer(), nullable=False),
        sa.Column("housing_charge_cents", sa.Integer(), nullable=False),
        sa.Column("move_in_date", sa.Date(), nullable=False),
        sa.Column("application_deadline", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status",
            sa.Enum("open", "closed", name="openingstatus"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "housing_charge_cents >= 0", name="ck_opening_housing_charge"
        ),
        sa.CheckConstraint(
            "unit_size_bedrooms BETWEEN 1 AND 3", name="ck_opening_unit_size"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_openings_status", "openings", ["status"])

    op.create_table(
        "application_participations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("application_id", sa.Integer(), nullable=False),
        sa.Column("opening_id", sa.Integer(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("declaration_accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retracted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"]),
        sa.ForeignKeyConstraint(["opening_id"], ["openings.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("application_id", "opening_id"),
    )
    op.create_index(
        "ix_application_participations_application_id",
        "application_participations",
        ["application_id"],
    )
    op.create_index(
        "ix_application_participations_opening_id",
        "application_participations",
        ["opening_id"],
    )

    op.create_table(
        "application_cycle_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("participation_id", sa.Integer(), nullable=False),
        sa.Column("primary_email", sa.String(length=320), nullable=False),
        sa.Column("applicant_name", sa.String(length=255), nullable=True),
        sa.Column("co_applicant_name", sa.String(length=255), nullable=True),
        sa.Column("answers", sa.JSON(), nullable=False),
        sa.Column("normalized", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("declaration_accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("frozen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["participation_id"], ["application_participations.id"]
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_application_cycle_snapshots_participation_id",
        "application_cycle_snapshots",
        ["participation_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_application_cycle_snapshots_participation_id",
        table_name="application_cycle_snapshots",
    )
    op.drop_table("application_cycle_snapshots")
    op.drop_index(
        "ix_application_participations_opening_id",
        table_name="application_participations",
    )
    op.drop_index(
        "ix_application_participations_application_id",
        table_name="application_participations",
    )
    op.drop_table("application_participations")
    op.drop_index("ix_openings_status", table_name="openings")
    op.drop_table("openings")

    with op.batch_alter_table("applications") as batch:
        batch.drop_index("ix_applications_deleted_at")
        batch.drop_index("ix_applications_submitted_at")
        batch.drop_column("retention_due_on")
        batch.drop_column("deleted_at")
        batch.drop_column("declaration_accepted_at")
        batch.drop_column("submitted_at")
        batch.drop_column("working_saved_at")
        batch.drop_column("working_content_hash")
        batch.drop_column("working_answers")
