"""Operational-metrics trends for the Observability tab.

Every completed run persisted a ``RunCostLedger`` + child ``RunPassCost`` rows (see
``cost_report``). This module reads those rows for cost, tokens, latency, cache-hit rate, and failure
counts per run and per pass, plus dimension-count-over-time for Rank. Pure aggregation:
no new capture beyond the ``duration_ms``/``failed_calls`` columns the passes already
record. Also the surface a later LLM-judge score would accrue on.
"""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import utc_isoformat
from app.db.models import Analysis, RunCostLedger
from app.schemas.observability import MetricsReport, PassTrendPoint, TrendPoint
from app.services.cost_report import CACHEABLE_PASSES, opening_label
from app.services.ranking.dimensions import current_dimension_report


def _rank_dimension_counts(db: Session) -> dict[int | None, list[int]]:
    """Live dimension counts in analysis order, separated by opening provenance."""
    counts: dict[int | None, list[int]] = defaultdict(list)
    for analysis in db.scalars(select(Analysis).order_by(Analysis.id.asc())):
        report = current_dimension_report(analysis)
        counts[analysis.opening_id].append(len(report.dimensions) if report else 0)
    return dict(counts)


def metrics_report(db: Session) -> MetricsReport:
    """Per-run and per-pass operational trends across all completed runs, oldest→newest."""
    ledgers = list(
        db.scalars(select(RunCostLedger).order_by(RunCostLedger.id.asc()))
    )
    dim_counts = _rank_dimension_counts(db)

    runs: list[TrendPoint] = []
    passes: list[PassTrendPoint] = []
    rank_seen: dict[int | None, int] = defaultdict(int)
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
            opening_counts = dim_counts.get(ledger.opening_id, [])
            index = rank_seen[ledger.opening_id]
            dimensions = opening_counts[index] if index < len(opening_counts) else None
            rank_seen[ledger.opening_id] += 1

        runs.append(
            TrendPoint(
                at=utc_isoformat(ledger.created_at),
                kind=ledger.kind,
                cost_usd=round(sum(r.cost_usd for r in rows), 6),
                input_tokens=sum(r.input_tokens for r in rows),
                output_tokens=sum(r.output_tokens for r in rows),
                duration_ms=sum(r.duration_ms for r in rows),
                failed_calls=sum(r.failed_calls for r in rows),
                cache_hit_rate=hit_rate,
                dimensions=dimensions,
                triggered_by=ledger.triggered_by.email if ledger.triggered_by else None,
                opening=opening_label(ledger),
            )
        )
        passes.extend(
            PassTrendPoint(
                at=utc_isoformat(ledger.created_at),
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
