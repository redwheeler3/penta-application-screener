"""replace opening snapshots with application versions

Revision ID: e0f1a2b3c4d5
Revises: d9e0f1a2b3c4
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e0f1a2b3c4d5"
down_revision: str | None = "d9e0f1a2b3c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "application_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("application_id", sa.Integer(), nullable=False),
        sa.Column("answers", sa.JSON(), nullable=False),
        sa.Column("normalized", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("declaration_accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_application_versions_application_id",
        "application_versions",
        ["application_id"],
    )
    op.execute(
        "INSERT INTO application_versions "
        "(application_id, answers, normalized, content_hash, submitted_at, "
        "declaration_accepted_at) "
        "SELECT p.application_id, s.answers, s.normalized, s.content_hash, "
        "s.submitted_at, s.declaration_accepted_at "
        "FROM application_cycle_snapshots s "
        "JOIN application_participations p ON p.id = s.participation_id"
    )
    op.drop_index(
        "ix_application_cycle_snapshots_participation_id",
        table_name="application_cycle_snapshots",
    )
    op.drop_table("application_cycle_snapshots")
    with op.batch_alter_table("application_participations") as batch:
        batch.alter_column("submitted_at", new_column_name="applied_at")
        batch.alter_column("retracted_at", new_column_name="withdrawn_at")
        batch.drop_column("declaration_accepted_at")


def downgrade() -> None:
    with op.batch_alter_table("application_participations") as batch:
        batch.add_column(
            sa.Column("declaration_accepted_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch.alter_column("withdrawn_at", new_column_name="retracted_at")
        batch.alter_column("applied_at", new_column_name="submitted_at")
    op.execute(
        "UPDATE application_participations SET "
        "declaration_accepted_at = submitted_at"
    )
    with op.batch_alter_table("application_participations") as batch:
        batch.alter_column("declaration_accepted_at", nullable=False)
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
        sa.Column(
            "frozen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
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
    op.drop_index(
        "ix_application_versions_application_id",
        table_name="application_versions",
    )
    op.drop_table("application_versions")
