"""split ranking_runs into analyses + member_rankings (M15 slice 1b)

M15 makes ranking per-member. ``ranking_runs`` fused the shared AI output (dimension_report,
rank_inputs_fingerprint, source_sync, the 1:1 audit) with one committee-wide view
(run_state = tiers + badges + proposals). This splits it:

  - ``analyses`` — the shared, compute-once AI output (one current). Takes the audit child,
    renamed ``analysis_audit`` (FK ranking_runs->analyses).
  - ``member_rankings`` — one per (analysis, member): that member's run_state. Keyed unique
    on (analysis_id, user_id).

Backfill (in Python — never CAST): each ranking_run becomes an analysis with the SAME id (so
creation-order correlation with rank ledgers, and any id references, stay intact); its audit
row is copied to analysis_audit; and its run_state becomes ONE member_rankings row owned by the
sole existing member (the single-tenant reality today — there is exactly one user, id-ordered
first = the founding admin). A ranking_run with no user to own it (empty users table) is
dropped — there is no member whose view it could be, and pre-user runs predate any tiering worth
keeping.

Reversible: downgrade recombines analysis + the (single) member_ranking back into ranking_runs.
Under real multi-member data the recombine would be lossy (N views collapse to one), but at
this single-member stage it round-trips exactly. Back up the .db before running.

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-07-24
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c3d4e5f6a7b8"
down_revision: str | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()

    # 1. New shared tables. analyses mirrors ranking_runs minus run_state; analysis_audit
    #    mirrors ranking_run_audit with the FK renamed to analysis_id.
    op.create_table(
        "analyses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_sync_run_id", sa.Integer(), nullable=True),
        sa.Column("dimension_report", sa.JSON(), nullable=False),
        sa.Column("rank_inputs_fingerprint", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False,
        ),
        sa.ForeignKeyConstraint(["source_sync_run_id"], ["sync_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_analyses_rank_inputs_fingerprint"), "analyses",
        ["rank_inputs_fingerprint"], unique=False,
    )
    op.create_table(
        "analysis_audit",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("analysis_id", sa.Integer(), nullable=False),
        sa.Column("discovery_narrative", sa.Text(), nullable=True),
        sa.Column("match", sa.JSON(), nullable=True),
        sa.Column("fan_out", sa.JSON(), nullable=True),
        sa.Column("decompose", sa.JSON(), nullable=True),
        sa.Column("consolidate", sa.JSON(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False,
        ),
        sa.ForeignKeyConstraint(["analysis_id"], ["analyses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_analysis_audit_analysis_id"), "analysis_audit", ["analysis_id"], unique=True,
    )
    op.create_table(
        "member_rankings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("analysis_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("run_state", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False,
        ),
        sa.ForeignKeyConstraint(["analysis_id"], ["analyses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("analysis_id", "user_id"),
    )
    op.create_index(
        op.f("ix_member_rankings_analysis_id"), "member_rankings", ["analysis_id"], unique=False,
    )
    op.create_index(
        op.f("ix_member_rankings_user_id"), "member_rankings", ["user_id"], unique=False,
    )

    # 2. Backfill. The single existing member owns every run's view (single-tenant today).
    owner_id = conn.execute(sa.text("SELECT id FROM users ORDER BY id LIMIT 1")).scalar()

    runs = conn.execute(
        sa.text(
            "SELECT id, source_sync_run_id, dimension_report, rank_inputs_fingerprint, "
            "run_state, created_at, updated_at FROM ranking_runs ORDER BY id"
        )
    ).mappings().all()
    for r in runs:
        conn.execute(
            sa.text(
                "INSERT INTO analyses "
                "(id, source_sync_run_id, dimension_report, rank_inputs_fingerprint, "
                " created_at, updated_at) "
                "VALUES (:id, :ssr, :report, :fp, :created, :updated)"
            ),
            {
                "id": r["id"], "ssr": r["source_sync_run_id"],
                "report": r["dimension_report"], "fp": r["rank_inputs_fingerprint"],
                "created": r["created_at"], "updated": r["updated_at"],
            },
        )
        # One member_ranking owning this run's view — only when there is a member to own it.
        if owner_id is not None:
            conn.execute(
                sa.text(
                    "INSERT INTO member_rankings "
                    "(analysis_id, user_id, run_state, created_at, updated_at) "
                    "VALUES (:aid, :uid, :state, :created, :updated)"
                ),
                {
                    "aid": r["id"], "uid": owner_id, "state": r["run_state"],
                    "created": r["created_at"], "updated": r["updated_at"],
                },
            )

    # Copy the audit rows, repointing run_id -> analysis_id (analysis.id == old run.id).
    conn.execute(
        sa.text(
            "INSERT INTO analysis_audit "
            "(id, analysis_id, discovery_narrative, match, fan_out, decompose, consolidate, "
            " created_at, updated_at) "
            "SELECT id, run_id, discovery_narrative, match, fan_out, decompose, consolidate, "
            " created_at, updated_at FROM ranking_run_audit"
        )
    )

    # 3. Drop the old tables (audit first — it FKs ranking_runs).
    op.drop_table("ranking_run_audit")
    op.drop_table("ranking_runs")


def downgrade() -> None:
    conn = op.get_bind()

    op.create_table(
        "ranking_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_sync_run_id", sa.Integer(), nullable=True),
        sa.Column("dimension_report", sa.JSON(), nullable=False),
        sa.Column("rank_inputs_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("run_state", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False,
        ),
        sa.ForeignKeyConstraint(["source_sync_run_id"], ["sync_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_ranking_runs_rank_inputs_fingerprint"), "ranking_runs",
        ["rank_inputs_fingerprint"], unique=False,
    )
    op.create_table(
        "ranking_run_audit",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("discovery_narrative", sa.Text(), nullable=True),
        sa.Column("match", sa.JSON(), nullable=True),
        sa.Column("fan_out", sa.JSON(), nullable=True),
        sa.Column("decompose", sa.JSON(), nullable=True),
        sa.Column("consolidate", sa.JSON(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False,
        ),
        sa.ForeignKeyConstraint(["run_id"], ["ranking_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_ranking_run_audit_run_id"), "ranking_run_audit", ["run_id"], unique=True,
    )

    # Recombine: each analysis + its member_ranking (the sole one, at this stage) → a
    # ranking_run. An analysis with no member_ranking recombines with an empty run_state.
    analyses = conn.execute(
        sa.text(
            "SELECT id, source_sync_run_id, dimension_report, rank_inputs_fingerprint, "
            "created_at, updated_at FROM analyses ORDER BY id"
        )
    ).mappings().all()
    for a in analyses:
        state = conn.execute(
            sa.text(
                "SELECT run_state FROM member_rankings WHERE analysis_id = :aid ORDER BY id LIMIT 1"
            ),
            {"aid": a["id"]},
        ).scalar()
        conn.execute(
            sa.text(
                "INSERT INTO ranking_runs "
                "(id, source_sync_run_id, dimension_report, rank_inputs_fingerprint, "
                " run_state, created_at, updated_at) "
                "VALUES (:id, :ssr, :report, :fp, :state, :created, :updated)"
            ),
            {
                "id": a["id"], "ssr": a["source_sync_run_id"],
                "report": a["dimension_report"], "fp": a["rank_inputs_fingerprint"],
                "state": state if state is not None else "{}",
                "created": a["created_at"], "updated": a["updated_at"],
            },
        )
    conn.execute(
        sa.text(
            "INSERT INTO ranking_run_audit "
            "(id, run_id, discovery_narrative, match, fan_out, decompose, consolidate, "
            " created_at, updated_at) "
            "SELECT id, analysis_id, discovery_narrative, match, fan_out, decompose, "
            " consolidate, created_at, updated_at FROM analysis_audit"
        )
    )

    op.drop_table("member_rankings")
    op.drop_table("analysis_audit")
    op.drop_table("analyses")
