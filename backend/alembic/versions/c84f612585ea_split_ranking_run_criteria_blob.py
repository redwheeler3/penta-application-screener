"""split ranking_runs.criteria blob into typed columns + ranking_run_audit

M14 Phase 5. The one opaque ``criteria`` JSON blob (12 keys mixing data, committee state,
and audit trails) becomes:
  - ``dimension_report`` — JSON column (the run's dimensions)
  - ``rank_inputs_fingerprint`` — indexed String column (the out-of-date signal)
  - ``run_state`` — JSON column = {tiers, new_dimension_keys, proposed_dimensions}
    (derived ``weights`` dropped — always re-derived from tiers)
  - ``ranking_run_audit`` — new 1:1 table for the 5 audit blobs (discovery_narrative +
    match/fan_out/decompose/consolidate); ``consolidate`` keeps only pairs+narrative
    (the merge map lives once in dimension_aliases)

Also drops the vestigial ``ranking_runs.name`` / ``.status`` (constant, never rendered),
the dead ``criteria.discovery_model_id`` key (written, never read), and ``sync_runs.notes``
(dead). Data is migrated in Python (extract the JSON, never CAST(text AS JSON) — SQLite
silently drops on a failed cast). Back up the .db before running.

Revision ID: c84f612585ea
Revises: 30c9cad8f673
Create Date: 2026-07-20
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c84f612585ea"
down_revision: str | None = "30c9cad8f673"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()

    # 1. New audit table (1:1 with ranking_runs).
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
    op.create_index("ix_ranking_run_audit_run_id", "ranking_run_audit", ["run_id"], unique=True)

    # 2. New columns on ranking_runs (nullable/temp defaults for the backfill pass).
    with op.batch_alter_table("ranking_runs") as batch:
        batch.add_column(sa.Column("dimension_report", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("rank_inputs_fingerprint", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("run_state", sa.JSON(), nullable=True))
    op.create_index(
        "ix_ranking_runs_rank_inputs_fingerprint", "ranking_runs", ["rank_inputs_fingerprint"]
    )

    # 3. Backfill from the criteria blob — in Python, never CAST(text AS JSON).
    rows = conn.execute(sa.text("SELECT id, criteria FROM ranking_runs")).fetchall()
    for run_id, criteria_raw in rows:
        criteria = json.loads(criteria_raw) if isinstance(criteria_raw, str) else (criteria_raw or {})

        dimension_report = criteria.get("dimension_report") or {}
        run_state = {
            "tiers": criteria.get("tiers") or [],
            "new_dimension_keys": criteria.get("new_dimension_keys") or [],
            "proposed_dimensions": criteria.get("proposed_dimensions") or [],
        }
        conn.execute(
            sa.text(
                "UPDATE ranking_runs SET dimension_report = :dr, "
                "rank_inputs_fingerprint = :fp, run_state = :rs WHERE id = :id"
            ),
            {
                "dr": json.dumps(dimension_report),
                "fp": criteria.get("rank_inputs_fingerprint"),
                "rs": json.dumps(run_state),
                "id": run_id,
            },
        )

        # The consolidate audit drops its stored `merges` map (dimension_aliases is the
        # truth; the view re-derives it from the merged pairs).
        consolidate = criteria.get("consolidate_audit")
        if consolidate is not None:
            consolidate = {
                "pairs": consolidate.get("pairs", []),
                "narrative": consolidate.get("narrative"),
            }
        audit = {
            "discovery_narrative": criteria.get("discovery_narrative"),
            "match": criteria.get("match_audit"),
            "fan_out": criteria.get("fan_out_audit"),
            "decompose": criteria.get("decompose_audit"),
            "consolidate": consolidate,
        }
        # Only create an audit row when the run actually captured something.
        if any(v is not None for v in audit.values()):
            conn.execute(
                sa.text(
                    "INSERT INTO ranking_run_audit "
                    "(run_id, discovery_narrative, match, fan_out, decompose, consolidate) "
                    "VALUES (:run_id, :dn, :m, :fo, :dc, :cs)"
                ),
                {
                    "run_id": run_id,
                    "dn": audit["discovery_narrative"],
                    "m": json.dumps(audit["match"]) if audit["match"] is not None else None,
                    "fo": json.dumps(audit["fan_out"]) if audit["fan_out"] is not None else None,
                    "dc": json.dumps(audit["decompose"]) if audit["decompose"] is not None else None,
                    "cs": json.dumps(audit["consolidate"]) if audit["consolidate"] is not None else None,
                },
            )

    # 4. Make the two required columns non-nullable now they're backfilled, and drop the
    #    old blob + the vestigial columns.
    with op.batch_alter_table("ranking_runs") as batch:
        batch.alter_column("dimension_report", existing_type=sa.JSON(), nullable=False)
        batch.alter_column("run_state", existing_type=sa.JSON(), nullable=False)
        batch.drop_column("criteria")
        batch.drop_column("name")
        batch.drop_column("status")

    # 5. Drop the dead sync_runs.notes column.
    with op.batch_alter_table("sync_runs") as batch:
        batch.drop_column("notes")


def downgrade() -> None:
    # Recreate the old columns and fold the split data back into the criteria blob.
    with op.batch_alter_table("sync_runs") as batch:
        batch.add_column(sa.Column("notes", sa.Text(), nullable=True))

    with op.batch_alter_table("ranking_runs") as batch:
        batch.add_column(sa.Column("criteria", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("name", sa.String(length=255), nullable=True))
        batch.add_column(sa.Column("status", sa.String(length=80), nullable=True))

    conn = op.get_bind()
    audit_by_run = {
        row[0]: row
        for row in conn.execute(
            sa.text(
                "SELECT run_id, discovery_narrative, match, fan_out, decompose, consolidate "
                "FROM ranking_run_audit"
            )
        ).fetchall()
    }
    rows = conn.execute(
        sa.text("SELECT id, dimension_report, rank_inputs_fingerprint, run_state FROM ranking_runs")
    ).fetchall()
    for run_id, dr_raw, fp, rs_raw in rows:
        dr = json.loads(dr_raw) if isinstance(dr_raw, str) else (dr_raw or {})
        rs = json.loads(rs_raw) if isinstance(rs_raw, str) else (rs_raw or {})
        tiers = rs.get("tiers") or []
        dimension_keys = [d.get("key") for d in dr.get("dimensions", [])]
        # Re-derive the weights the old blob stored (top tier heaviest; uniform fallback).
        weights = _weights_from_tiers(dimension_keys, tiers)

        criteria = {
            "dimension_report": dr,
            "rank_inputs_fingerprint": fp,
            "tiers": tiers,
            "weights": weights,
            "new_dimension_keys": rs.get("new_dimension_keys") or [],
            "proposed_dimensions": rs.get("proposed_dimensions") or [],
            "discovery_model_id": None,  # was write-only; no value to restore
            "discovery_narrative": None,
            "match_audit": None,
            "fan_out_audit": None,
            "decompose_audit": None,
        }
        audit = audit_by_run.get(run_id)
        if audit is not None:
            _run, dn, m, fo, dc, cs = audit
            criteria["discovery_narrative"] = dn
            criteria["match_audit"] = json.loads(m) if isinstance(m, str) else m
            criteria["fan_out_audit"] = json.loads(fo) if isinstance(fo, str) else fo
            criteria["decompose_audit"] = json.loads(dc) if isinstance(dc, str) else dc
            consolidate = json.loads(cs) if isinstance(cs, str) else cs
            if consolidate is not None:
                # Re-derive the merges map the old blob carried, from the merged pairs.
                consolidate["merges"] = {
                    p["drop"]: p["keep"] for p in consolidate.get("pairs", []) if p.get("merged")
                }
            criteria["consolidate_audit"] = consolidate

        conn.execute(
            sa.text(
                "UPDATE ranking_runs SET criteria = :c, name = :n, status = :s WHERE id = :id"
            ),
            {"c": json.dumps(criteria), "n": "Ranking run", "s": "patterns_discovered", "id": run_id},
        )

    with op.batch_alter_table("ranking_runs") as batch:
        batch.alter_column("criteria", existing_type=sa.JSON(), nullable=False)
        batch.alter_column("name", existing_type=sa.String(length=255), nullable=False)
        batch.alter_column("status", existing_type=sa.String(length=80), nullable=False)
        batch.drop_index("ix_ranking_runs_rank_inputs_fingerprint")
        batch.drop_column("run_state")
        batch.drop_column("rank_inputs_fingerprint")
        batch.drop_column("dimension_report")

    op.drop_index("ix_ranking_run_audit_run_id", table_name="ranking_run_audit")
    op.drop_table("ranking_run_audit")


def _weights_from_tiers(dimension_keys: list, tier_layout: list) -> dict:
    """Standalone copy of ranking_run.weights_from_tiers, so downgrade doesn't import app
    code (which will have moved on). Top tier heaviest; uniform fallback when nothing placed."""
    keys = set(dimension_keys)
    tier_count = len(tier_layout)
    placed: dict = {}
    for rank, tier in enumerate(tier_layout):
        weight = float(tier_count - rank)
        for key in tier.get("dimension_keys", []):
            if key in keys:
                placed[key] = weight
    if not placed:
        return dict.fromkeys(dimension_keys, 1.0)
    return {k: placed.get(k, 0.0) for k in dimension_keys}
