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

Milestone 8 seeds the run with an **equal-weight baseline** (``criteria.weights``,
one entry per dimension key, all equal) and a default ``shortlist_size``. The AI
never proposes importance — discovering the axes is its job; deciding what
matters is the committee's, and milestone 9's narrowing answers are the only
thing that moves these weights off equal.
"""

from __future__ import annotations

import hashlib

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.schemas import PoolPatternReport
from app.db.models import ScreeningRun

# The shortlist line the committee reads top-down to; a starting point only, not
# a hard rule (SPEC "Interactive Screening": a likely target ~20, not hard-coded).
DEFAULT_SHORTLIST_SIZE = 20

# Equal-weight baseline: every discovered dimension starts equally important.
INITIAL_DIMENSION_WEIGHT = 1.0


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
            # Equal-weight baseline — the ranking engine reads this map, never a
            # per-dimension field, so it is the single seam M9's answers mutate.
            "weights": {
                d.key: INITIAL_DIMENSION_WEIGHT for d in report.dimensions
            },
            "shortlist_size": DEFAULT_SHORTLIST_SIZE,
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


def dimension_weights(run: ScreeningRun) -> dict[str, float]:
    """The run's per-dimension weights, defaulting to equal for any dimension
    missing from the stored map (e.g. a run created before weights were seeded).
    """
    stored = (run.criteria or {}).get("weights") or {}
    report = current_pattern_report(run)
    if report is None:
        return {k: float(v) for k, v in stored.items()}
    return {
        d.key: float(stored.get(d.key, INITIAL_DIMENSION_WEIGHT))
        for d in report.dimensions
    }


def shortlist_size(run: ScreeningRun) -> int:
    """The run's shortlist-line position, defaulting when unset."""
    return int((run.criteria or {}).get("shortlist_size", DEFAULT_SHORTLIST_SIZE))


def set_shortlist_size(db: Session, run: ScreeningRun, size: int) -> ScreeningRun:
    """Persist a new shortlist-line position. The line is a reading aid over the
    soft ranking — it never removes anyone — so any non-negative value is valid.
    """
    # criteria is a JSON column; reassign a new dict so SQLAlchemy sees the change.
    run.criteria = {**(run.criteria or {}), "shortlist_size": max(0, size)}
    db.commit()
    db.refresh(run)
    return run
