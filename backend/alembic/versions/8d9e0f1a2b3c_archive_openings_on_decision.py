"""archive openings and anchor retention on committee decisions

Revision ID: 8d9e0f1a2b3c
Revises: 7c8d9e0f1a2b
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "8d9e0f1a2b3c"
down_revision: str | None = "7c8d9e0f1a2b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("openings") as batch:
        batch.add_column(sa.Column("decided_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("decided_by_user_id", sa.Integer()))
        batch.add_column(
            sa.Column(
                "no_household_selected",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            )
        )
        batch.create_foreign_key(
            "fk_openings_decided_by_user",
            "users",
            ["decided_by_user_id"],
            ["id"],
        )
        batch.create_index("ix_openings_decided_at", ["decided_at"], unique=False)

    op.execute(
        """
        UPDATE openings
        SET decided_at = COALESCE(
                no_household_selected_at,
                (SELECT MIN(p.outcome_decided_at)
                 FROM application_participations AS p
                 WHERE p.opening_id = openings.id AND p.outcome IS NOT NULL)
            ),
            decided_by_user_id = COALESCE(
                no_household_selected_by_user_id,
                (SELECT p.outcome_decided_by_user_id
                 FROM application_participations AS p
                 WHERE p.opening_id = openings.id AND p.outcome IS NOT NULL
                 ORDER BY p.id LIMIT 1)
            ),
            no_household_selected = CASE
                WHEN no_household_selected_at IS NOT NULL THEN 1 ELSE 0
            END
        """
    )

    with op.batch_alter_table("openings") as batch:
        batch.drop_constraint(
            "fk_openings_no_household_selected_by_user", type_="foreignkey"
        )
        batch.drop_column("no_household_selected_by_user_id")
        batch.drop_column("no_household_selected_at")

    with op.batch_alter_table("application_participations") as batch:
        batch.drop_constraint(
            "fk_application_participations_outcome_user", type_="foreignkey"
        )
        batch.drop_column("outcome_decided_by_user_id")
        batch.drop_column("outcome_decided_at")

    with op.batch_alter_table("applicant_drafts") as batch:
        batch.alter_column("retention_due_on", new_column_name="expires_on")

    op.execute(
        """
        UPDATE applicant_drafts
        SET expires_on = COALESCE(
            (SELECT date(MAX(o.application_close_date), '+1 day')
             FROM json_each(applicant_drafts.working_opening_ids) AS selected
             JOIN openings AS o ON o.id = selected.value),
            expires_on
        )
        """
    )
    op.execute(
        """
        UPDATE applications
        SET retention_due_on = CASE
            WHEN submitted_at IS NULL THEN COALESCE(
                (SELECT date(MAX(o.application_close_date), '+1 day')
                 FROM json_each(applications.working_opening_ids) AS selected
                 JOIN openings AS o ON o.id = selected.value),
                retention_due_on
            )
            WHEN EXISTS (
                SELECT 1 FROM application_participations AS p
                WHERE p.application_id = applications.id
                  AND p.outcome = 'selected'
            ) THEN (
                SELECT date(MAX(o.decided_at), '+7 years')
                FROM application_participations AS p
                JOIN openings AS o ON o.id = p.opening_id
                WHERE p.application_id = applications.id
                  AND p.outcome = 'selected'
            )
            WHEN EXISTS (
                SELECT 1 FROM application_participations AS p
                JOIN openings AS o ON o.id = p.opening_id
                WHERE p.application_id = applications.id
                  AND o.decided_at IS NULL
            ) THEN NULL
            ELSE (
                SELECT date(MAX(o.decided_at), '+1 year')
                FROM application_participations AS p
                JOIN openings AS o ON o.id = p.opening_id
                WHERE p.application_id = applications.id
            )
        END
        """
    )


def downgrade() -> None:
    with op.batch_alter_table("applicant_drafts") as batch:
        batch.alter_column("expires_on", new_column_name="retention_due_on")

    with op.batch_alter_table("application_participations") as batch:
        batch.add_column(sa.Column("outcome_decided_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("outcome_decided_by_user_id", sa.Integer()))
        batch.create_foreign_key(
            "fk_application_participations_outcome_user",
            "users",
            ["outcome_decided_by_user_id"],
            ["id"],
        )
    op.execute(
        """
        UPDATE application_participations
        SET outcome_decided_at = (
                SELECT decided_at FROM openings
                WHERE openings.id = application_participations.opening_id
            ),
            outcome_decided_by_user_id = (
                SELECT decided_by_user_id FROM openings
                WHERE openings.id = application_participations.opening_id
            )
        WHERE outcome IS NOT NULL
        """
    )

    with op.batch_alter_table("openings") as batch:
        batch.add_column(sa.Column("no_household_selected_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("no_household_selected_by_user_id", sa.Integer()))
        batch.create_foreign_key(
            "fk_openings_no_household_selected_by_user",
            "users",
            ["no_household_selected_by_user_id"],
            ["id"],
        )
    op.execute(
        """
        UPDATE openings
        SET no_household_selected_at = CASE
                WHEN no_household_selected THEN decided_at ELSE NULL
            END,
            no_household_selected_by_user_id = CASE
                WHEN no_household_selected THEN decided_by_user_id ELSE NULL
            END
        """
    )
    with op.batch_alter_table("openings") as batch:
        batch.drop_index("ix_openings_decided_at")
        batch.drop_constraint("fk_openings_decided_by_user", type_="foreignkey")
        batch.drop_column("no_household_selected")
        batch.drop_column("decided_by_user_id")
        batch.drop_column("decided_at")
