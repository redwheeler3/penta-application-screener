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

# Passes that can reuse cached results. The others (pattern discovery, dimension
# matching) always call Bedrock fresh, so a "saved by cache" figure is N/A for them —
# the UI shows "—", never $0, so structural absence of caching doesn't read as failure.
CACHEABLE_PASSES = {"Screening", "Essay analysis", "Dimension scoring"}


def _pass(
    label: str,
    calls: int,
    input_tokens: int,
    output_tokens: int,
    cost: float,
    cached_count: int = 0,
    cached_saved: float = 0.0,
) -> CostPass:
    return CostPass(
        pass_label=label,
        calls=calls,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=round(cost, 6),
        cacheable=label in CACHEABLE_PASSES,
        cached_count=cached_count,
        cached_saved_usd=round(cached_saved, 6),
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
        subtotal_saved_usd=round(sum(p.cached_saved_usd for p in passes), 6),
    )


def _cache_by_pass(db: Session) -> dict[str, tuple[int, float]]:
    """Cumulative cache reuse per pass label — (cached_count, saved_usd) — summed from
    the run-cost ledger. Only covers runs since ledgering began (historical reuse was
    never recorded — the result cache has no hit counter). Fine here: the local DB
    resets before go-live."""
    agg: dict[str, tuple[int, float]] = {}
    for row in db.scalars(select(RunCostLedger)):
        for p in row.passes:
            count, saved = agg.get(p["label"], (0, 0.0))
            agg[p["label"]] = (
                count + int(p.get("cached_count") or 0),
                saved + float(p.get("cached_saved_usd") or 0.0),
            )
    return agg


def cost_report(db: Session) -> CostReport:
    """Cumulative AI spend across all runs, grouped by the run that triggers each pass.
    Spend is exact (a plain sum of every stored cost); cache savings come from the
    run-cost ledger (see ``_saved_by_pass``).

    Screen runs the screening pass; Rank runs essay analysis → pattern discovery →
    dimension matching → dimension scoring (essay analysis is part of Rank, not Screen).
    """
    all_runs = list(db.scalars(select(RankingRun)))
    # A match pass runs only when there's a prior run to match against, so it's absent
    # on first runs; count only runs that actually stored a match cost.
    match_runs = [r for r in all_runs if (r.criteria or {}).get("match_cost_usd")]
    # Count only runs that actually stored a decompose cost (fan-out redesign onward).
    decompose_runs = [r for r in all_runs if (r.criteria or {}).get("decompose_cost_usd")]
    cache = _cache_by_pass(db)  # label → (cached_count, saved_usd)

    def cached(label: str) -> dict:
        count, saved = cache.get(label, (0, 0.0))
        return {"cached_count": count, "cached_saved": saved}

    screen = _group(
        "Screen",
        [_pass("Screening", *_sum_rows(db, ApplicationAIResult.kind == SCREENING), **cached("Screening"))],
    )
    rank = _group(
        "Rank",
        [
            _pass("Essay analysis", *_sum_rows(db, ApplicationAIResult.kind == ESSAY),
                  **cached("Essay analysis")),
            # Discovery and match are separate Bedrock calls (Sonnet vs. Haiku), stored
            # and attributed separately. Cost-only (no tokens stored). Never cacheable.
            # Runs created before the discovery/match cost split fold their match cost
            # into discovery_cost_usd — a minor historical over-attribution, not worth
            # resetting real cost history over.
            _pass("Pattern discovery", len(all_runs), 0, 0, _summed(all_runs, "discovery_cost_usd")),
            # Decomposition settles the K fan-out reports into one set — its own call,
            # cost-only, attributed separately. Only runs from the fan-out redesign store
            # it; older runs have 0, so they simply don't contribute.
            _pass("Dimension decomposition", len(decompose_runs), 0, 0,
                  _summed(all_runs, "decompose_cost_usd")),
            _pass("Dimension matching", len(match_runs), 0, 0, _summed(all_runs, "match_cost_usd")),
            _pass("Dimension scoring", *_sum_rows(db, ApplicationAIResult.kind.startswith(SCORING_PREFIX)),
                  **cached("Dimension scoring")),
        ],
    )
    groups = [screen, rank]
    return CostReport(
        groups=groups,
        total_cost_usd=round(sum(g.subtotal_usd for g in groups), 6),
        total_saved_usd=round(sum(g.subtotal_saved_usd for g in groups), 6),
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
        # cacheable isn't stored on the ledger row (it's a fixed property of the pass),
        # so derive it here from the pass label.
        passes=[LastRunPass(**p, cacheable=p["label"] in CACHEABLE_PASSES) for p in row.passes],
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
    when we don't): a past run's stored ``fresh_usd`` for a pass already captures its
    real cost shape — for scoring, carry-forward reuse plus newly-minted fresh scoring;
    for discovery/decompose, the real output size at the current prompt (so it self-
    corrects when a prompt change moves the token count, instead of a hand-tuned
    constant going stale). Weighted toward the most recent run because early runs
    (fresh pool, bigger output) shouldn't dominate.

    Returns None when no Rank run has recorded this pass yet — the caller falls back to
    a seed estimate. Only reads the ledger (the honest per-run source); does not see the
    *current* cache state, so a pool that just grew is under-predicted until the next run
    records it (documented caveat, not a blend).

    Minor edge: a pass that records ``fresh_usd=0`` on a first run (match, which is
    skipped with no prior history) will pull the average down if such a run falls in the
    recency window. Tolerated, not filtered — recency-weighting favours later non-zero
    runs and first-runs age out fast; the seed fallback already covers the first re-run.
    """
    rows = list(
        db.scalars(
            select(RunCostLedger)
            .where(RunCostLedger.kind == "rank")
            .order_by(RunCostLedger.id.desc())
            .limit(_SCORING_HISTORY_WINDOW)
        )
    )
    # rows are newest→oldest; pull each run's scoring-pass fresh spend.
    fresh: list[float] = []
    for row in rows:
        for p in row.passes:
            if p["label"] == pass_label:
                fresh.append(float(p.get("fresh_usd") or 0.0))
                break
    if not fresh:
        return None
    # Linear recency weights: newest gets the largest weight (len), oldest gets 1.
    weights = list(range(len(fresh), 0, -1))
    weighted = sum(f * w for f, w in zip(fresh, weights, strict=True))
    return weighted / sum(weights)
