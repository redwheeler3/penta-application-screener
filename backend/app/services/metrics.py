"""Operational-metrics trends for the Insights tab (M13 Pillar 3).

Every completed run persisted a ``RunCostLedger`` + child ``RunPassCost`` rows (see
``cost_report``). Pillar 1 reads those for *spend*; this reads the same rows for
*operational trends over runs* — cost, tokens, latency, cache-hit rate, and failure
counts per run and per pass, plus dimension-count-over-time for Rank. Pure aggregation:
no new capture beyond the ``duration_ms``/``failed_calls`` columns the passes already
record. Also the surface a later LLM-judge score would accrue on.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import RankingRun, RunCostLedger
from app.schemas.insights import MetricsReport, PassTrendPoint, TrendPoint
from app.services.cost_report import CACHEABLE_PASSES
from app.services.ranking_run import current_dimension_report


def _rank_dimension_counts(db: Session) -> list[int]:
    """Live dimension count per Rank ledger, in ledger order. Rank ledgers and
    ``RankingRun``s are created 1:1 in the same request, so the Nth rank ledger pairs
    with the Nth ranking run — correlate by creation order (no FK between them)."""
    counts: list[int] = []
    for run in db.scalars(select(RankingRun).order_by(RankingRun.id.asc())):
        report = current_dimension_report(run)
        counts.append(len(report.dimensions) if report else 0)
    return counts


def metrics_report(db: Session) -> MetricsReport:
    """Per-run and per-pass operational trends across all completed runs, oldest→newest."""
    ledgers = list(
        db.scalars(select(RunCostLedger).order_by(RunCostLedger.id.asc()))
    )
    dim_counts = _rank_dimension_counts(db)

    runs: list[TrendPoint] = []
    passes: list[PassTrendPoint] = []
    rank_seen = 0  # index into dim_counts, advanced per rank ledger
    for ledger in ledgers:
        rows = ledger.passes
        # Cache-hit rate over cacheable units only: a pass that can't cache (discovery)
        # shouldn't dilute the rate toward 0. None when there was no cacheable work.
        cacheable = [r for r in rows if r.label in CACHEABLE_PASSES]
        cached = sum(r.cached_count for r in cacheable)
        fresh = sum(r.calls for r in cacheable)
        hit_rate = cached / (cached + fresh) if (cached + fresh) else None

        dimensions = None
        if ledger.kind == "rank":
            dimensions = dim_counts[rank_seen] if rank_seen < len(dim_counts) else None
            rank_seen += 1

        runs.append(
            TrendPoint(
                at=ledger.created_at.isoformat(),
                kind=ledger.kind,
                cost_usd=round(sum(r.cost_usd for r in rows), 6),
                input_tokens=sum(r.input_tokens for r in rows),
                output_tokens=sum(r.output_tokens for r in rows),
                duration_ms=sum(r.duration_ms for r in rows),
                failed_calls=sum(r.failed_calls for r in rows),
                cache_hit_rate=hit_rate,
                dimensions=dimensions,
            )
        )
        passes.extend(
            PassTrendPoint(
                at=ledger.created_at.isoformat(),
                label=r.label,
                cost_usd=round(r.cost_usd, 6),
                input_tokens=r.input_tokens,
                output_tokens=r.output_tokens,
                duration_ms=r.duration_ms,
                failed_calls=r.failed_calls,
            )
            for r in rows
        )
    return MetricsReport(runs=runs, passes=passes)
