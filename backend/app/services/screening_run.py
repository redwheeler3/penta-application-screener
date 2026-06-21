"""Screening-run persistence (milestone 7).

A ``ScreeningRun`` holds the run-scoped products of pattern discovery: the
discovered ``PoolPatternReport`` and a short hash of its dimension set. The
per-candidate dimension scores are *not* stored here — they live in
``ApplicationAIResult`` rows under ``kind = "dimension_scoring:<dims_hash>"``, so
the run's ``dims_hash`` is the join back to a candidate's scores (see SPEC
"Pattern Discovery And Dimension Scoring"). The table existed unused before this
milestone; here is where it first gets wired.

Milestone 7 keeps the lifecycle minimal: rediscovering patterns creates a new
run, and "the current run" is simply the most recent one. Weights, answers, and
rankings accrete onto the same run in milestones 8-9.
"""

from __future__ import annotations

import hashlib

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.schemas import PoolPatternReport
from app.db.models import ScreeningRun


def dimensions_hash(report: PoolPatternReport) -> str:
    """Stable short hash over the dimension *keys* of a pattern report.

    Folded into the scoring pass's cache ``kind`` so two runs with different
    dimension sets get distinct cached scores instead of colliding. Keys only
    (sorted): the identity of a dimension set is which axes it scores on, not
    their prose definitions or proposed weights.
    """
    keys = sorted(d.key for d in report.dimensions)
    basis = "\n".join(keys)
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:12]


def create_run(
    db: Session,
    *,
    report: PoolPatternReport,
    model_id: str,
    narrative: str | None,
    cost_usd: float,
    name: str = "Screening run",
) -> ScreeningRun:
    """Persist a freshly discovered pattern report as a new screening run."""
    run = ScreeningRun(
        name=name,
        status="patterns_discovered",
        criteria={
            "pattern_report": report.model_dump(mode="json"),
            "dims_hash": dimensions_hash(report),
            "discovery_model_id": model_id,
            "discovery_narrative": narrative,
            "discovery_cost_usd": round(cost_usd, 6),
        },
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def get_current_run(db: Session) -> ScreeningRun | None:
    """The most recent screening run, or None if discovery has never run."""
    return db.scalar(select(ScreeningRun).order_by(ScreeningRun.id.desc()).limit(1))


def current_pattern_report(run: ScreeningRun) -> PoolPatternReport | None:
    """Parse the stored ``PoolPatternReport`` from a run's criteria, if present."""
    payload = (run.criteria or {}).get("pattern_report")
    if payload is None:
        return None
    return PoolPatternReport.model_validate(payload)
