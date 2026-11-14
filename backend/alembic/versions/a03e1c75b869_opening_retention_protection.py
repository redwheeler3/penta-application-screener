"""Protect retained applicants during opening preparation and intake."""

from datetime import datetime
from zoneinfo import ZoneInfo

import sqlalchemy as sa

from alembic import op

revision = "a03e1c75b869"
down_revision = "f92d0b64a758"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("openings", "publication_request_id", new_column_name="creation_request_id")
    op.alter_column("openings", "publication_request", new_column_name="creation_request")
    op.create_table("opening_retention_protections",
        sa.Column("opening_id", sa.Integer(), sa.ForeignKey("openings.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("application_id", sa.Integer(), sa.ForeignKey("applications.id", ondelete="CASCADE"), primary_key=True))
    op.create_index("ix_opening_retention_protections_application_id", "opening_retention_protections", ["application_id"])
    today = datetime.now(ZoneInfo("America/Vancouver")).date().isoformat()
    op.get_bind().execute(sa.text("""
        INSERT INTO opening_retention_protections (opening_id, application_id)
        SELECT o.id, a.id FROM openings o CROSS JOIN applications a
        WHERE o.intake_mode = 'applications' AND o.decided_at IS NULL
          AND o.application_close_date >= :today
          AND a.submitted_at IS NOT NULL AND a.withdrawn_at IS NULL
          AND (a.retention_due_on IS NULL OR a.retention_due_on > :today)
          AND NOT EXISTS (SELECT 1 FROM application_participations p
                          WHERE p.application_id = a.id AND p.outcome = 'selected')
    """), {"today": today})


def downgrade():
    op.drop_table("opening_retention_protections")
    op.alter_column("openings", "creation_request_id", new_column_name="publication_request_id")
    op.alter_column("openings", "creation_request", new_column_name="publication_request")
