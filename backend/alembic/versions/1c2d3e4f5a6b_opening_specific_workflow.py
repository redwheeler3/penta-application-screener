"""scope committee workflow state to openings

Revision ID: 1c2d3e4f5a6b
Revises: f0a1b2c3d4e5
Create Date: 2026-08-31
"""

import json
from collections.abc import Sequence
from datetime import datetime
from zoneinfo import ZoneInfo

import sqlalchemy as sa

from alembic import op

revision: str = "1c2d3e4f5a6b"
down_revision: str | None = "f0a1b2c3d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEFAULT_RULES = {
    "income_min": 70_000,
    "income_max": 150_000,
    "min_adult_age": 18,
    "max_child_age": 17,
    "min_children": 1,
    "max_children": 4,
    "max_dogs": 1,
    "max_cats": 1,
    "allow_other_pets": False,
    "employment_requirement": "none",
    "disabled_checks": [],
}


def _json(value) -> dict:
    if value is None:
        return dict(_DEFAULT_RULES)
    return json.loads(value) if isinstance(value, str) else dict(value)


def _intake_opening_ids(connection) -> list[int]:
    return list(
        connection.execute(
            sa.text("SELECT id FROM openings WHERE intake_mode = 'applications' ORDER BY id")
        ).scalars()
    )


def _candidate_opening_ids(connection, application_id: int) -> list[int]:
    return list(
        connection.execute(
            sa.text(
                "SELECT DISTINCT p.opening_id "
                "FROM application_participations p "
                "JOIN applications a ON a.id = p.application_id "
                "JOIN openings o ON o.id = p.opening_id "
                "WHERE p.application_id = :application_id "
                "AND p.withdrawn_at IS NULL "
                "AND a.withdrawn_at IS NULL "
                "AND (a.retention_due_on IS NULL OR a.retention_due_on >= :today) "
                "AND o.intake_mode = 'applications' "
                "AND NOT EXISTS ("
                "  SELECT 1 FROM application_participations selected "
                "  WHERE selected.application_id = p.application_id "
                "  AND selected.outcome = 'selected'"
                ") ORDER BY p.opening_id"
            ),
            {
                "application_id": application_id,
                "today": datetime.now(ZoneInfo("America/Vancouver")).date(),
            },
        ).scalars()
    )


def upgrade() -> None:
    connection = op.get_bind()
    opening_ids = _intake_opening_ids(connection)

    op.create_table(
        "opening_rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("opening_id", sa.Integer(), nullable=False),
        sa.Column("rules", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False,
        ),
        sa.ForeignKeyConstraint(["opening_id"], ["openings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("opening_id"),
    )
    op.create_index(
        op.f("ix_opening_rules_opening_id"), "opening_rules", ["opening_id"], unique=True
    )
    stored_default = connection.execute(
        sa.text("SELECT value FROM admin_settings WHERE key = 'committee_default_rules'")
    ).scalar_one_or_none()
    default_rules = _json(stored_default)
    for opening_id in opening_ids:
        connection.execute(
            sa.text(
                "INSERT INTO opening_rules (opening_id, rules, created_at, updated_at) "
                "VALUES (:opening_id, :rules, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"opening_id": opening_id, "rules": json.dumps(default_rules)},
        )

    op.create_table(
        "member_rules_m24",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("opening_id", sa.Integer(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("rules", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False,
        ),
        sa.ForeignKeyConstraint(["opening_id"], ["openings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("opening_id", "user_id"),
    )
    member_rules = connection.execute(
        sa.text("SELECT user_id, rules, created_at, updated_at FROM member_rules ORDER BY id")
    ).mappings().all()
    for row in member_rules:
        contexts = opening_ids or [None]
        for opening_id in contexts:
            connection.execute(
                sa.text(
                    "INSERT INTO member_rules_m24 "
                    "(opening_id, user_id, rules, created_at, updated_at) "
                    "VALUES (:opening_id, :user_id, :rules, :created_at, :updated_at)"
                ),
                {**row, "opening_id": opening_id},
            )
    op.drop_table("member_rules")
    op.rename_table("member_rules_m24", "member_rules")
    op.create_index(op.f("ix_member_rules_opening_id"), "member_rules", ["opening_id"])
    op.create_index(op.f("ix_member_rules_user_id"), "member_rules", ["user_id"])

    op.create_table(
        "member_eligibility_m24",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("opening_id", sa.Integer(), nullable=True),
        sa.Column("application_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "status", sa.Enum("eligible", "ineligible", name="applicationstatus"),
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
        sa.ForeignKeyConstraint(["opening_id"], ["openings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("opening_id", "application_id", "user_id"),
    )
    overrides = connection.execute(
        sa.text(
            "SELECT application_id, user_id, status, reviewed_fingerprint, created_at, updated_at "
            "FROM member_eligibility ORDER BY id"
        )
    ).mappings().all()
    for row in overrides:
        contexts = _candidate_opening_ids(connection, row["application_id"]) or [None]
        for opening_id in contexts:
            connection.execute(
                sa.text(
                    "INSERT INTO member_eligibility_m24 "
                    "(opening_id, application_id, user_id, status, reviewed_fingerprint, "
                    " created_at, updated_at) "
                    "VALUES (:opening_id, :application_id, :user_id, :status, "
                    ":reviewed_fingerprint, :created_at, :updated_at)"
                ),
                {**row, "opening_id": opening_id},
            )
    op.drop_table("member_eligibility")
    op.rename_table("member_eligibility_m24", "member_eligibility")
    op.create_index(
        op.f("ix_member_eligibility_opening_id"), "member_eligibility", ["opening_id"]
    )
    op.create_index(
        op.f("ix_member_eligibility_application_id"),
        "member_eligibility", ["application_id"],
    )
    op.create_index(
        op.f("ix_member_eligibility_user_id"), "member_eligibility", ["user_id"]
    )

    shortlist_rows = connection.execute(
        sa.text(
            "SELECT application_id, added_by_user_id, created_at, updated_at "
            "FROM application_shortlist ORDER BY id"
        )
    ).mappings().all()
    mapped_shortlist: list[tuple[dict, int]] = []
    for row in shortlist_rows:
        contexts = _candidate_opening_ids(connection, row["application_id"])
        if len(contexts) != 1:
            raise RuntimeError(
                "Shared shortlist migration requires an explicit opening mapping for "
                f"{len(contexts)}-context application {row['application_id']}."
            )
        mapped_shortlist.append((dict(row), contexts[0]))
    op.create_table(
        "application_shortlist_m24",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("opening_id", sa.Integer(), nullable=False),
        sa.Column("application_id", sa.Integer(), nullable=False),
        sa.Column("added_by_user_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False,
        ),
        sa.ForeignKeyConstraint(["opening_id"], ["openings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["added_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("opening_id", "application_id"),
    )
    for row, opening_id in mapped_shortlist:
        connection.execute(
            sa.text(
                "INSERT INTO application_shortlist_m24 "
                "(opening_id, application_id, added_by_user_id, created_at, updated_at) "
                "VALUES (:opening_id, :application_id, :added_by_user_id, :created_at, :updated_at)"
            ),
            {**row, "opening_id": opening_id},
        )
    op.drop_table("application_shortlist")
    op.rename_table("application_shortlist_m24", "application_shortlist")
    op.create_index(
        op.f("ix_application_shortlist_opening_id"),
        "application_shortlist", ["opening_id"],
    )
    op.create_index(
        op.f("ix_application_shortlist_application_id"),
        "application_shortlist", ["application_id"],
    )

    with op.batch_alter_table("analyses") as batch:
        batch.add_column(sa.Column("opening_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_analyses_opening_id_openings", "openings", ["opening_id"], ["id"],
            ondelete="CASCADE",
        )
        batch.create_index("ix_analyses_opening_id", ["opening_id"])
    with op.batch_alter_table("run_cost_ledger") as batch:
        batch.add_column(sa.Column("opening_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_run_cost_ledger_opening_id_openings", "openings", ["opening_id"], ["id"],
            ondelete="SET NULL",
        )
        batch.create_index("ix_run_cost_ledger_opening_id", ["opening_id"])

    # A one-opening deployment has only one possible owner: preserve every paid analysis,
    # member ranking, and cost row there without making the committee rerun anything.
    # With several openings, preserve a global analysis only when its complete stored
    # fingerprint maps to exactly one scoped pool; ambiguous history remains nullable.
    if len(opening_ids) == 1:
        connection.execute(
            sa.text("UPDATE analyses SET opening_id = :opening_id WHERE opening_id IS NULL"),
            {"opening_id": opening_ids[0]},
        )
        connection.execute(
            sa.text(
                "UPDATE run_cost_ledger SET opening_id = :opening_id "
                "WHERE opening_id IS NULL"
            ),
            {"opening_id": opening_ids[0]},
        )
    elif len(opening_ids) > 1:
        _assign_unambiguous_analyses(connection, opening_ids)

    connection.execute(
        sa.text("DELETE FROM admin_settings WHERE key = 'committee_default_rules'")
    )


def _assign_unambiguous_analyses(connection, opening_ids: list[int]) -> None:
    from sqlalchemy.orm import Session

    from app.schemas.settings import AppSettings
    from app.services.ranking.freshness import rank_inputs_fingerprint
    from app.services.settings import get_app_settings

    db = Session(bind=connection)
    settings: AppSettings = get_app_settings(db)
    fingerprint_by_opening = {
        opening_id: rank_inputs_fingerprint(db, opening_id, settings)
        for opening_id in opening_ids
    }
    analyses = connection.execute(
        sa.text(
            "SELECT id, rank_inputs_fingerprint FROM analyses "
            "WHERE opening_id IS NULL AND rank_inputs_fingerprint IS NOT NULL"
        )
    ).mappings()
    for analysis in analyses:
        matches = [
            opening_id
            for opening_id, fingerprint in fingerprint_by_opening.items()
            if fingerprint == analysis["rank_inputs_fingerprint"]
        ]
        if len(matches) == 1:
            connection.execute(
                sa.text("UPDATE analyses SET opening_id = :opening_id WHERE id = :id"),
                {"opening_id": matches[0], "id": analysis["id"]},
            )

def downgrade() -> None:
    connection = op.get_bind()
    latest_rules = connection.execute(
        sa.text("SELECT rules FROM opening_rules ORDER BY opening_id DESC LIMIT 1")
    ).scalar_one_or_none()
    connection.execute(
        sa.text(
            "INSERT INTO admin_settings (key, value, created_at, updated_at) "
            "VALUES ('committee_default_rules', :rules, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ),
        {"rules": json.dumps(_json(latest_rules))},
    )

    with op.batch_alter_table("run_cost_ledger") as batch:
        batch.drop_index("ix_run_cost_ledger_opening_id")
        batch.drop_constraint("fk_run_cost_ledger_opening_id_openings", type_="foreignkey")
        batch.drop_column("opening_id")
    with op.batch_alter_table("analyses") as batch:
        batch.drop_index("ix_analyses_opening_id")
        batch.drop_constraint("fk_analyses_opening_id_openings", type_="foreignkey")
        batch.drop_column("opening_id")

    # Downgrade is intentionally lossy: collapse opening-specific working state to the
    # lowest-opening-id row for each pre-M24 identity.
    op.create_table(
        "application_shortlist_legacy",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("application_id", sa.Integer(), nullable=False),
        sa.Column("added_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["added_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("application_id"),
    )
    connection.execute(
        sa.text(
            "INSERT INTO application_shortlist_legacy "
            "(application_id, added_by_user_id, created_at, updated_at) "
            "SELECT application_id, added_by_user_id, MIN(created_at), MAX(updated_at) "
            "FROM application_shortlist GROUP BY application_id"
        )
    )
    op.drop_table("application_shortlist")
    op.rename_table("application_shortlist_legacy", "application_shortlist")
    op.create_index(
        op.f("ix_application_shortlist_application_id"),
        "application_shortlist", ["application_id"], unique=True,
    )

    op.create_table(
        "member_rules_legacy",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("rules", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )
    connection.execute(
        sa.text(
            "INSERT INTO member_rules_legacy (user_id, rules, created_at, updated_at) "
            "SELECT user_id, rules, created_at, updated_at FROM member_rules m "
            "WHERE id = (SELECT id FROM member_rules x WHERE x.user_id = m.user_id "
            "ORDER BY x.opening_id, x.id LIMIT 1)"
        )
    )
    op.drop_table("member_rules")
    op.rename_table("member_rules_legacy", "member_rules")
    op.create_index(op.f("ix_member_rules_user_id"), "member_rules", ["user_id"], unique=True)

    op.create_table(
        "member_eligibility_legacy",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("application_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "status", sa.Enum("eligible", "ineligible", name="applicationstatus"),
            nullable=False,
        ),
        sa.Column("reviewed_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("application_id", "user_id"),
    )
    connection.execute(
        sa.text(
            "INSERT INTO member_eligibility_legacy "
            "(application_id, user_id, status, reviewed_fingerprint, created_at, updated_at) "
            "SELECT application_id, user_id, status, reviewed_fingerprint, created_at, updated_at "
            "FROM member_eligibility m WHERE id = (SELECT id FROM member_eligibility x "
            "WHERE x.application_id = m.application_id AND x.user_id = m.user_id "
            "ORDER BY x.opening_id, x.id LIMIT 1)"
        )
    )
    op.drop_table("member_eligibility")
    op.rename_table("member_eligibility_legacy", "member_eligibility")
    op.create_index(
        op.f("ix_member_eligibility_application_id"),
        "member_eligibility", ["application_id"],
    )
    op.create_index(
        op.f("ix_member_eligibility_user_id"), "member_eligibility", ["user_id"]
    )
    op.drop_index(op.f("ix_opening_rules_opening_id"), table_name="opening_rules")
    op.drop_table("opening_rules")
