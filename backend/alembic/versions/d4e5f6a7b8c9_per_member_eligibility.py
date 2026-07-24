"""per-member eligibility: member_eligibility table + drop stored status (M15 slice 1c)

M15 1c makes applicant eligibility PER-MEMBER and computed on read. Eligibility
(`eligible`/`ineligible`) is no longer stored on the applicant: the machine verdict is
derived on read from the applicant's shared ``hard_filter_reasons`` + cached screening
flags, and a member's *human override* of that verdict lives in a new sparse table. So:

  - ``member_eligibility`` — one row per (application, member) ONLY where that member
    overrode the machine verdict. The row's existence IS the human override (there is no
    ``status_source`` column: a row = source ``human``). ``reviewed_fingerprint`` snapshots
    the findings when the member set the override, for the staleness nudge.
  - ``applications`` LOSES ``status``, ``status_source``, ``reviewed_fingerprint`` — they
    were stored derivations that became per-member. ``hard_filter_reasons`` stays (the
    shared machine baseline).

Backfill (in Python — never CAST): the sole existing member owns the overrides. For each
application whose stored ``status_source`` was ``human`` (there is exactly one today —
Jasmine Roy, app id 55, status ``eligible``), insert a ``member_eligibility`` row owned by
the id-ordered-first user, carrying that app's ``status`` + ``reviewed_fingerprint``.
Skipped entirely if the users table is empty (no member to own an override).

Reversible, but LOSSY for N members: downgrade re-adds the three columns and recombines
each member_eligibility row back onto its application (``status_source='human'``). At the
single-member stage today it round-trips exactly; with several members it would collapse N
per-member overrides onto one application row. Machine statuses are NOT recomputed on
downgrade — the re-added ``status``/``status_source`` default to eligible/untouched for
apps without an override, which is only correct for clean apps. Back up the .db before
running.

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-07-24
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: str | None = "c3d4e5f6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()

    # 1. The sparse per-member override table.
    op.create_table(
        "member_eligibility",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("application_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("eligible", "ineligible", name="applicationstatus"),
            nullable=False,
        ),
        sa.Column("reviewed_fingerprint", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False,
        ),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("application_id", "user_id"),
    )
    op.create_index(
        op.f("ix_member_eligibility_application_id"),
        "member_eligibility", ["application_id"], unique=False,
    )
    op.create_index(
        op.f("ix_member_eligibility_user_id"),
        "member_eligibility", ["user_id"], unique=False,
    )

    # 2. Backfill: the id-ordered-first member owns every human override that existed on the
    #    applications table (single-tenant reality today). No owner -> nothing to migrate.
    owner_id = conn.execute(sa.text("SELECT id FROM users ORDER BY id LIMIT 1")).scalar()
    if owner_id is not None:
        overrides = conn.execute(
            sa.text(
                "SELECT id, status, reviewed_fingerprint FROM applications "
                "WHERE status_source = 'human'"
            )
        ).mappings().all()
        for row in overrides:
            conn.execute(
                sa.text(
                    "INSERT INTO member_eligibility "
                    "(application_id, user_id, status, reviewed_fingerprint) "
                    "VALUES (:aid, :uid, :status, :fp)"
                ),
                {
                    "aid": row["id"], "uid": owner_id,
                    "status": row["status"], "fp": row["reviewed_fingerprint"],
                },
            )

    # 3. Drop the stored-derivation columns (SQLite needs batch mode to rebuild the table).
    #    hard_filter_reasons stays — it is the shared machine baseline. Drop the indexes on
    #    status/status_source first, so the table rebuild doesn't try to recreate an index
    #    on a column that's going away.
    op.drop_index("ix_applications_status", table_name="applications")
    op.drop_index("ix_applications_status_source", table_name="applications")
    with op.batch_alter_table("applications") as batch:
        batch.drop_column("status")
        batch.drop_column("status_source")
        batch.drop_column("reviewed_fingerprint")


def downgrade() -> None:
    conn = op.get_bind()

    # Re-add the columns with defaults matching the pre-1c schema. Existing rows get
    # eligible/untouched/NULL; the recombine below then stamps the human overrides back.
    with op.batch_alter_table("applications") as batch:
        batch.add_column(
            sa.Column(
                "status",
                sa.Enum("eligible", "ineligible", name="applicationstatus"),
                nullable=False, server_default="eligible",
            )
        )
        batch.add_column(
            sa.Column(
                "status_source",
                sa.Enum("untouched", "rules", "ai", "human", name="statussource"),
                nullable=False, server_default="untouched",
            )
        )
        batch.add_column(sa.Column("reviewed_fingerprint", sa.String(length=64), nullable=True))
    op.create_index("ix_applications_status", "applications", ["status"], unique=False)
    op.create_index(
        "ix_applications_status_source", "applications", ["status_source"], unique=False
    )

    # Recombine: fold each member_eligibility row back onto its application as a human
    # override. Lossy for N members (they collapse onto one row); exact at one member.
    overrides = conn.execute(
        sa.text(
            "SELECT application_id, status, reviewed_fingerprint FROM member_eligibility "
            "ORDER BY id"
        )
    ).mappings().all()
    for row in overrides:
        conn.execute(
            sa.text(
                "UPDATE applications SET status = :status, status_source = 'human', "
                "reviewed_fingerprint = :fp WHERE id = :aid"
            ),
            {"status": row["status"], "fp": row["reviewed_fingerprint"], "aid": row["application_id"]},
        )

    op.drop_index(op.f("ix_member_eligibility_user_id"), table_name="member_eligibility")
    op.drop_index(op.f("ix_member_eligibility_application_id"), table_name="member_eligibility")
    op.drop_table("member_eligibility")
