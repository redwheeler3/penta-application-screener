"""Operational-metrics trends for the Observability tab.

Each recorded attempt persists a ``RunCostLedger`` + child ``RunPassCost`` rows (see
``cost_report``). This module reads those rows for cost, tokens, latency, cache-hit rate, and failure
counts per run and per pass, plus status and the final dimension count captured with each completed Rank.
These are persisted attempt facts; unrelated analyses do not supply metrics.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.core.time import utc_isoformat
from app.db.models import RunCostLedger
from app.schemas.observability import MetricsReport, PassTrendPoint, TrendPoint
from app.services.cost_report import CACHEABLE_PASSES, opening_label


def metrics_report(db: Session) -> MetricsReport:
    """Per-run and per-pass operational trends across recorded attempts, oldest→newest."""
    ledgers = list(
        db.scalars(select(RunCostLedger).options(
            selectinload(RunCostLedger.passes),
            joinedload(RunCostLedger.triggered_by),
            joinedload(RunCostLedger.opening),
        ).order_by(RunCostLedger.id.asc()))
    )

    runs: list[TrendPoint] = []
    passes: list[PassTrendPoint] = []
    for ledger in ledgers:
        rows = ledger.passes
        interrupted = ledger.failed_pass == "Interrupted"
        # Cache-hit rate over cacheable units only: a pass that can't cache (discovery)
        # shouldn't dilute the rate toward 0. None when there was no cacheable work.
        cacheable = [r for r in rows if r.label in CACHEABLE_PASSES]
        cached = sum(r.cached_count for r in cacheable)
        fresh = sum(r.fresh_units or 0 for r in cacheable)
        measured = all(r.fresh_units is not None for r in cacheable)
        hit_rate = cached / (cached + fresh) if measured and (cached + fresh) else None

        runs.append(
            TrendPoint(
                at=utc_isoformat(ledger.created_at),
                kind=ledger.kind,
                status=ledger.status, failed_pass=ledger.failed_pass,
                cost_usd=round(sum(r.cost_usd for r in rows), 6),
                input_tokens=sum(r.input_tokens for r in rows),
                output_tokens=sum(r.output_tokens for r in rows),
                duration_ms=None if interrupted else sum(r.duration_ms for r in rows),
                failed_calls=sum(r.failed_calls for r in rows),
                cache_hit_rate=hit_rate,
                dimensions=ledger.dimension_count,
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
                duration_ms=None if interrupted else r.duration_ms,
                failed_calls=r.failed_calls,
            )
            for r in rows
        )
    return MetricsReport(runs=runs, passes=passes)
