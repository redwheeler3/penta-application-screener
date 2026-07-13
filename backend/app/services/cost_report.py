"""Cost aggregation for the Insights tab (M13 Pillar 1).

Every AI pass — pool-level (discovery, decompose, match, consolidate) and per-
application (screening, scoring) alike — records its spend the same way: a ``PassCost``
folded into a ``RunPassCost`` row, one per pass, under a ``RunCostLedger`` header per
completed run. That single table is the source for both cost surfaces here:
  - **cumulative** — every dollar/token ever spent, summed across all runs' pass rows.
  - **last-run** — the most recent Screen and Rank, each pass's fresh-vs-cached split.

Both are exact and now carry a token + model breakdown, because the ledger is written as
each run completes (the only point the fresh/cached split is known) — ``ApplicationAIResult``
is a reuse cache with no run-id stamp, so per-run cost can't be reconstructed from it
after the fact. (This is unrelated to the spending cap, which bounds each individual run
before it starts; the lifetime total has no ceiling of its own.)
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.pricing import PassCost
from app.db.models import RunCostLedger, RunPassCost
from app.schemas.insights import (
    CostGroup,
    CostPass,
    CostReport,
    LastRunCost,
    LastRunPass,
    LastRunsReport,
)

# The canonical pass labels per user-facing run, and the SINGLE SOURCE OF TRUTH for
# "which passes exist." Every run records exactly these rows (a pass that made no call
# this run still records a zero row), so both surfaces cover the full set by construction
# and can't drift. Add a pass here first, then have its run record a RunPassCost for it.
RANK_PASS_LABELS = [
    "Pattern discovery",
    "Dimension decomposition",
    "Dimension matching",
    "Dimension scoring",
    "Dimension consolidation",
]
SCREEN_PASS_LABELS = ["Screening"]

# Passes that can reuse cached results. The others (discovery, decomposition, matching,
# consolidation) always call Bedrock fresh, so a "saved by cache" figure is N/A — the UI
# shows "—", never $0, so structural absence of caching doesn't read as failure.
CACHEABLE_PASSES = {"Screening", "Dimension scoring"}


# --- Recording (both Screen and Rank write here) ----------------------------------


def record_run_cost(
    db: Session,
    *,
    kind: str,
    passes: dict[str, PassCost],
    durations_ms: dict[str, int] | None = None,
) -> None:
    """Persist a completed run's per-pass cost (``kind`` = "screen" | "rank"), one
    ``RunPassCost`` row per pass, under a header row. Called as the run's stream finishes
    — the only point the fresh/cached split is known. ``passes`` maps each canonical pass
    label to its ``PassCost`` (a pass that made no call still passes a zero cost, so the
    row set always covers the canonical labels). ``durations_ms`` maps a label to the
    pass's wall-clock (measured by the caller, not summed from PassCost — see the model
    docstring); a label absent from it records 0. Commits its own rows so a later failure
    can't lose them.
    """
    durations_ms = durations_ms or {}
    header = RunCostLedger(
        kind=kind,
        passes=[
            RunPassCost(
                label=label,
                model_id=cost.model_id,
                calls=cost.calls,
                input_tokens=cost.input_tokens,
                output_tokens=cost.output_tokens,
                cost_usd=round(cost.cost_usd, 6),
                cached_count=cost.cached_count,
                cached_saved_usd=round(cost.cached_saved_usd, 6),
                duration_ms=durations_ms.get(label, 0),
                failed_calls=cost.failed_calls,
            )
            for label, cost in passes.items()
        ],
    )
    db.add(header)
    db.commit()


# --- Cumulative report (all-time spend, grouped by triggering run) ----------------


def _cost_pass(label: str, rows: list[RunPassCost]) -> CostPass:
    """Fold every recorded row for one pass label into its cumulative CostPass."""
    return CostPass(
        pass_label=label,
        calls=sum(r.calls for r in rows),
        input_tokens=sum(r.input_tokens for r in rows),
        output_tokens=sum(r.output_tokens for r in rows),
        cost_usd=round(sum(r.cost_usd for r in rows), 6),
        cacheable=label in CACHEABLE_PASSES,
        cached_count=sum(r.cached_count for r in rows),
        cached_saved_usd=round(sum(r.cached_saved_usd for r in rows), 6),
    )


def _group(run_label: str, passes: list[CostPass]) -> CostGroup:
    return CostGroup(
        run_label=run_label,
        passes=passes,
        subtotal_usd=round(sum(p.cost_usd for p in passes), 6),
        subtotal_saved_usd=round(sum(p.cached_saved_usd for p in passes), 6),
    )


def cost_report(db: Session) -> CostReport:
    """Cumulative AI spend across all runs, grouped by the run that triggers each pass.
    A plain sum over every recorded ``RunPassCost`` — spend, tokens, and cache savings
    all exact.

    Screen runs the screening pass; Rank runs pattern discovery → dimension
    decomposition → dimension matching → dimension scoring → dimension consolidation.
    """
    by_label: dict[str, list[RunPassCost]] = {}
    for row in db.scalars(select(RunPassCost)):
        by_label.setdefault(row.label, []).append(row)

    screen = _group("Screen", [_cost_pass(label, by_label.get(label, [])) for label in SCREEN_PASS_LABELS])
    rank = _group("Rank", [_cost_pass(label, by_label.get(label, [])) for label in RANK_PASS_LABELS])
    groups = [screen, rank]
    return CostReport(
        groups=groups,
        total_cost_usd=round(sum(g.subtotal_usd for g in groups), 6),
        total_saved_usd=round(sum(g.subtotal_saved_usd for g in groups), 6),
    )


# --- Last-run report (most recent Screen / Rank, fresh vs. cached) ----------------


def _last_run(db: Session, kind: str) -> LastRunCost | None:
    row = db.scalar(
        select(RunCostLedger)
        .where(RunCostLedger.kind == kind)
        .order_by(RunCostLedger.id.desc())
        .limit(1)
    )
    if row is None:
        return None
    passes = [
        LastRunPass(
            label=p.label,
            fresh_usd=round(p.cost_usd, 6),
            fresh_calls=p.calls,
            input_tokens=p.input_tokens,
            output_tokens=p.output_tokens,
            cached_count=p.cached_count,
            cached_saved_usd=round(p.cached_saved_usd, 6),
            cacheable=p.label in CACHEABLE_PASSES,
        )
        for p in row.passes
    ]
    return LastRunCost(
        kind=row.kind,
        at=row.created_at.isoformat(),
        fresh_usd=round(sum(p.fresh_usd for p in passes), 6),
        cached_saved_usd=round(sum(p.cached_saved_usd for p in passes), 6),
        passes=passes,
    )


def last_runs_report(db: Session) -> LastRunsReport:
    """The most recent Screen and the most recent Rank, each with its fresh spend and
    cache savings. Either is null if that run type hasn't completed since ledgering
    began."""
    return LastRunsReport(screen=_last_run(db, "screen"), rank=_last_run(db, "rank"))


# How many recent Rank runs to average when predicting a re-run's fresh scoring cost.
_SCORING_HISTORY_WINDOW = 5


def recent_pass_fresh_usd(db: Session, pass_label: str = "Dimension scoring") -> float | None:
    """A recency-weighted average of what recent Rank runs actually spent (fresh) on the
    named pass — the MEASURED predictor of a re-run's cost for that pass.

    The principle (per .clinerules: estimate from history when we have it, seed only
    when we don't): a past run's stored fresh cost for a pass already captures its real
    cost shape — for scoring, carry-forward reuse plus newly-minted fresh scoring; for
    discovery/decompose, the real output size at the current prompt (so it self-corrects
    when a prompt change moves the token count, instead of a hand-tuned constant going
    stale). Weighted toward the most recent run because early runs (fresh pool, bigger
    output) shouldn't dominate.

    Returns None when no Rank run has recorded this pass yet — the caller falls back to
    a seed estimate. Only reads the ledger (the honest per-run source); does not see the
    *current* cache state, so a pool that just grew is under-predicted until the next run
    records it (documented caveat, not a blend).

    Minor edge: a pass that records $0 on a first run (match, which is skipped with no
    prior history) will pull the average down if such a run falls in the recency window.
    Tolerated, not filtered — recency-weighting favours later non-zero runs and first-runs
    age out fast; the seed fallback already covers the first re-run.
    """
    rows = list(
        db.scalars(
            select(RunPassCost)
            .join(RunCostLedger, RunPassCost.run_id == RunCostLedger.id)
            .where(RunCostLedger.kind == "rank", RunPassCost.label == pass_label)
            .order_by(RunCostLedger.id.desc())
            .limit(_SCORING_HISTORY_WINDOW)
        )
    )
    # rows are newest→oldest (one per recent Rank, since each run records one row per pass).
    fresh = [float(r.cost_usd) for r in rows]
    if not fresh:
        return None
    # Linear recency weights: newest gets the largest weight (len), oldest gets 1.
    weights = list(range(len(fresh), 0, -1))
    weighted = sum(f * w for f, w in zip(fresh, weights, strict=True))
    return weighted / sum(weights)
