"""Cost aggregation for the Insights tab (M13 Pillar 1).

AI spend lives in two places:
  - ``ApplicationAIResult`` rows — the per-application passes (screening, essay
    analysis, dimension scoring), with tokens + cost per call.
  - ``RankingRun.criteria["discovery_cost_usd"]`` — the run-level discovery + match
    passes, cost only (no token breakdown is stored for them).

Only a **cumulative** figure is surfaced — every dollar ever spent across all runs,
which is exact. (This is unrelated to the spending cap, which bounds each individual
run — Screen or Rank — before it starts; the lifetime total has no ceiling of its
own.) A per-run "what did this run cost" figure is deliberately NOT shown:
``ApplicationAIResult`` is a cache keyed by (candidate, dimension, prompt-version) for
reuse, with no run-id stamp, so a
surviving dimension's rows accumulate across runs and prompt versions — the current
run's true cost can't be reconstructed after the fact without over-counting. Exact
per-run cost would need run attribution stamped at write time (a later capture task).
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import ApplicationAIResult, RankingRun, RunCostLedger
from app.schemas.insights import (
    CostGroup,
    CostPass,
    CostReport,
    LastRunCost,
    LastRunPass,
    LastRunsReport,
)

SCREENING = "screening"
ESSAY = "essay_analysis"
SCORING_PREFIX = "dimension_scoring:"


def _pass(label: str, calls: int, input_tokens: int, output_tokens: int, cost: float) -> CostPass:
    return CostPass(
        pass_label=label,
        calls=calls,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=round(cost, 6),
    )


def _sum_rows(db: Session, kind_filter) -> tuple[int, int, int, float]:
    """(calls, input_tokens, output_tokens, cost) over ApplicationAIResult rows
    matching ``kind_filter`` (a SQLAlchemy where-clause)."""
    row = db.execute(
        select(
            func.count(ApplicationAIResult.id),
            func.coalesce(func.sum(ApplicationAIResult.input_tokens), 0),
            func.coalesce(func.sum(ApplicationAIResult.output_tokens), 0),
            func.coalesce(func.sum(ApplicationAIResult.cost_usd), 0.0),
        ).where(kind_filter)
    ).one()
    return int(row[0]), int(row[1]), int(row[2]), float(row[3])


def _summed(runs: list[RankingRun], key: str) -> float:
    """Summed value of a cost key across runs (cost-only fields; no tokens)."""
    return sum(float((r.criteria or {}).get(key) or 0.0) for r in runs)


def _group(run_label: str, passes: list[CostPass]) -> CostGroup:
    return CostGroup(
        run_label=run_label,
        passes=passes,
        subtotal_usd=round(sum(p.cost_usd for p in passes), 6),
    )


def cost_report(db: Session) -> CostReport:
    """Cumulative AI spend across all runs, grouped by the run that triggers each pass.
    Exact — a plain sum of every stored cost.

    Screen runs the screening pass; Rank runs essay analysis → pattern discovery →
    dimension matching → dimension scoring (essay analysis is part of Rank, not Screen).
    """
    all_runs = list(db.scalars(select(RankingRun)))
    # A match pass runs only when there's a prior run to match against, so it's absent
    # on first runs; count only runs that actually stored a match cost.
    match_runs = [r for r in all_runs if (r.criteria or {}).get("match_cost_usd")]

    screen = _group(
        "Screen",
        [_pass("Screening", *_sum_rows(db, ApplicationAIResult.kind == SCREENING))],
    )
    rank = _group(
        "Rank",
        [
            _pass("Essay analysis", *_sum_rows(db, ApplicationAIResult.kind == ESSAY)),
            # Discovery and match are separate Bedrock calls (Sonnet vs. Haiku), stored
            # and attributed separately. Cost-only (no tokens stored). Runs created
            # before the split fold their match cost into discovery_cost_usd — a minor
            # historical over-attribution to discovery, not worth resetting real cost
            # history over.
            _pass("Pattern discovery", len(all_runs), 0, 0, _summed(all_runs, "discovery_cost_usd")),
            _pass("Dimension matching", len(match_runs), 0, 0, _summed(all_runs, "match_cost_usd")),
            _pass("Dimension scoring", *_sum_rows(db, ApplicationAIResult.kind.startswith(SCORING_PREFIX))),
        ],
    )
    groups = [screen, rank]
    return CostReport(
        groups=groups,
        total_cost_usd=round(sum(g.subtotal_usd for g in groups), 6),
    )


# --- Per-run ledger (last Screen / last Rank cost + cache breakdown) --------------


def ledger_pass(
    label: str, *, fresh_usd: float, fresh_calls: int, cached_count: int, cached_saved_usd: float
) -> dict:
    """One per-pass ledger entry. Kept as a plain dict — it's serialized straight into
    the ledger row's JSON ``passes`` column."""
    return {
        "label": label,
        "fresh_usd": round(fresh_usd, 6),
        "fresh_calls": fresh_calls,
        "cached_count": cached_count,
        "cached_saved_usd": round(cached_saved_usd, 6),
    }


def record_run_cost(db: Session, *, kind: str, passes: list[dict]) -> None:
    """Persist a completed run's cost + cache breakdown (``kind`` = "screen" | "rank").
    Called as the run's stream finishes — the only point the fresh/cached split is
    known. Commits its own row so a later failure can't lose it."""
    db.add(
        RunCostLedger(
            kind=kind,
            fresh_usd=round(sum(p["fresh_usd"] for p in passes), 6),
            cached_saved_usd=round(sum(p["cached_saved_usd"] for p in passes), 6),
            passes=passes,
        )
    )
    db.commit()


def _last_run(db: Session, kind: str) -> LastRunCost | None:
    row = db.scalar(
        select(RunCostLedger)
        .where(RunCostLedger.kind == kind)
        .order_by(RunCostLedger.id.desc())
        .limit(1)
    )
    if row is None:
        return None
    return LastRunCost(
        kind=row.kind,
        at=row.created_at.isoformat(),
        fresh_usd=row.fresh_usd,
        cached_saved_usd=row.cached_saved_usd,
        passes=[LastRunPass(**p) for p in row.passes],
    )


def last_runs_report(db: Session) -> LastRunsReport:
    """The most recent Screen and the most recent Rank, each with its fresh spend and
    cache savings. Either is null if that run type hasn't completed since ledgering
    began."""
    return LastRunsReport(screen=_last_run(db, "screen"), rank=_last_run(db, "rank"))
