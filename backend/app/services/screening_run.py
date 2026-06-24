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
from app.db.models import Application, ApplicationStatus, ScreeningRun

# The shortlist line the committee reads top-down to; a starting point only, not
# a hard rule (SPEC "Interactive Screening": a likely target ~20, not hard-coded).
DEFAULT_SHORTLIST_SIZE = 20

# Equal-weight baseline: every discovered dimension starts equally important.
INITIAL_DIMENSION_WEIGHT = 1.0


def pool_fingerprint(db: Session) -> str:
    """A stable hash of the eligible pool's inputs.

    The Rank chain (essays → criteria → scores) is a pure function of the
    eligible pool, so if this fingerprint is unchanged since the last completed
    run, re-running would only re-pay for an identical result — discovery is
    nondeterministic, so it would even churn the dimensions and force a needless
    full re-score. We gate on this to block a no-op Rank.

    Built from the sorted ``raw_row_hash`` of every eligible application, which
    captures the three things that should trigger a re-rank: a new applicant (new
    hash present), an edited application (its hash changes), and an eligibility
    flip (an app enters or leaves the eligible set). Status *source* and AI
    outputs are deliberately excluded — they don't change what the pool says.
    """
    hashes = db.scalars(
        select(Application.raw_row_hash)
        .where(Application.status == ApplicationStatus.ELIGIBLE)
        .order_by(Application.raw_row_hash)
    ).all()
    basis = "\n".join(hashes)
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


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
            # Fingerprint of the eligible pool this run was built from, so the next
            # Rank can detect an unchanged pool and skip a no-op re-run.
            "pool_fingerprint": pool_fingerprint(db),
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


def ranking_is_current(db: Session, run: ScreeningRun | None) -> bool:
    """True when ``run`` was built from the current eligible pool — i.e. its
    stored ``pool_fingerprint`` matches the pool now. A no-op Rank is blocked on
    this. False if there is no run, or the run predates fingerprinting (so it can
    always be brought current by re-running once).
    """
    if run is None:
        return False
    stored = (run.criteria or {}).get("pool_fingerprint")
    if not stored:
        return False
    return stored == pool_fingerprint(db)


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


def default_tier_layout(report: PoolPatternReport) -> list[dict]:
    """The opening tier layout: every dimension in one working tier, plus an empty
    Ignore tier. One non-ignore tier means every dimension gets equal weight — so
    this reproduces the M8 equal-weight baseline until the committee tiers.
    """
    return [
        {
            "id": "tier-1",
            "label": "All criteria",
            "dimension_keys": [d.key for d in report.dimensions],
            "ignore": False,
        },
        {"id": "ignore", "label": "Ignore", "dimension_keys": [], "ignore": True},
    ]


def tiers(run: ScreeningRun) -> list[dict]:
    """The run's tier layout, or the default (single working tier) when unset —
    e.g. a run created before M9, or one the committee has not tiered yet.
    """
    stored = (run.criteria or {}).get("tiers")
    if stored:
        return stored
    report = current_pattern_report(run)
    return default_tier_layout(report) if report is not None else []


def weights_from_tiers(
    dimension_keys: list[str], tier_layout: list[dict]
) -> dict[str, float]:
    """Derive per-dimension weights from a tier layout — the pure heart of M9.

    Non-ignore tiers are weighted by position, top to bottom: with ``n`` non-ignore
    tiers the top gets ``n``, the next ``n-1`` … down to ``1``; dimensions in the
    Ignore tier get ``0``. Equal within a tier. A dimension not placed in any tier
    falls back to the top weight so it still counts (e.g. a freshly added one); if
    there are no non-ignore tiers at all, everything is ``1.0`` so fit is not all
    zero. Only keys in ``dimension_keys`` are returned, so a stale tier entry that
    names a dropped dimension is ignored.
    """
    keys = set(dimension_keys)
    non_ignore_count = sum(1 for t in tier_layout if not t.get("ignore"))

    # Degenerate layout (no working tiers — everything ignored or no tiers at all)
    # would zero out every fit and make the ranking meaningless. The committee
    # can't have meant "rank on nothing," so fall back to uniform weights.
    if non_ignore_count == 0:
        return {key: 1.0 for key in dimension_keys}

    placed: dict[str, float] = {}
    rank = 0
    for tier in tier_layout:
        if tier.get("ignore"):
            weight = 0.0
        else:
            weight = float(non_ignore_count - rank)
            rank += 1
        for key in tier.get("dimension_keys", []):
            if key in keys:
                placed[key] = weight

    # An unplaced key (e.g. one just added to the run) still counts, at the top
    # weight, rather than silently dropping out.
    return {key: placed.get(key, float(non_ignore_count)) for key in dimension_keys}


def set_tiers(
    db: Session, run: ScreeningRun, tier_layout: list[dict]
) -> ScreeningRun:
    """Persist a new tier layout and the weights derived from it.

    The layout is the source of truth; ``criteria.weights`` is recomputed from it
    so the ranking engine (which reads ``weights``) stays untouched. Validates that
    every placed key is a real dimension of this run.
    """
    report = current_pattern_report(run)
    valid_keys = {d.key for d in report.dimensions} if report is not None else set()
    for tier in tier_layout:
        for key in tier.get("dimension_keys", []):
            if key not in valid_keys:
                raise ValueError(f"Unknown dimension key in tier layout: {key!r}")

    weights = weights_from_tiers(sorted(valid_keys), tier_layout)
    # criteria is a JSON column; reassign a new dict so SQLAlchemy sees the change.
    run.criteria = {**(run.criteria or {}), "tiers": tier_layout, "weights": weights}
    db.commit()
    db.refresh(run)
    return run


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
