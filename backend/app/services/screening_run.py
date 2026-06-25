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

Weights are **derived from the tier layout**, never proposed by the AI: the run
stores ``criteria.tiers`` (working tiers only — see ``weights_from_tiers``) and
``criteria.weights`` is recomputed from it. A fresh run opens with empty tiers, so
every dimension is unplaced and the derived weights fall back to a uniform
equal-weight baseline until the committee tiers. Discovering the axes is the AI's
job; deciding what matters is the committee's (milestone 9's tier-list).
"""

from __future__ import annotations

import hashlib

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.schemas import PoolPatternReport
from app.db.models import Application, ApplicationStatus, ScreeningRun


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
    tier_layout: list[dict] | None = None,
    new_dimension_keys: list[str] | None = None,
) -> ScreeningRun:
    """Persist a freshly discovered pattern report as a new screening run.

    ``tier_layout`` carries the committee's prior placements forward across a
    re-rank (see ``carry_forward_layout``); when omitted, the run opens with the
    default all-Ignore layout. Either way the run stores its tiers explicitly and
    derives ``weights`` from them, so the layout is the single source of truth.
    ``new_dimension_keys`` are the unmatched new dimensions (parked in Ignore) to
    flag in the UI; empty on a first run.
    """
    layout = tier_layout if tier_layout is not None else default_tier_layout()
    dimension_keys = [d.key for d in report.dimensions]
    run = ScreeningRun(
        name=name,
        status="patterns_discovered",
        criteria={
            "pattern_report": report.model_dump(mode="json"),
            "dims_hash": dimensions_hash(report),
            # Fingerprint of the eligible pool this run was built from, so the next
            # Rank can detect an unchanged pool and skip a no-op re-run.
            "pool_fingerprint": pool_fingerprint(db),
            # The tier layout is the source of truth; weights are derived from it
            # (the ranking engine reads weights, never tiers). A fresh all-Ignore
            # board derives uniform weights = the equal-weight baseline.
            "tiers": layout,
            "weights": weights_from_tiers(dimension_keys, layout),
            "new_dimension_keys": new_dimension_keys or [],
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
    """The run's per-dimension weights. ``create_run`` and ``set_tiers`` always
    write a complete map (derived from the tier layout), so this is a plain read.
    """
    return {k: float(v) for k, v in ((run.criteria or {}).get("weights") or {}).items()}


# The opening working tiers (most→least important). Empty, so every dimension is
# "ignored" by absence until the committee drags it into one — nothing influences
# the ranking until a human has weighed in ("the human decides what matters"). The
# Ignore zone is not stored; it is synthesized for display from whatever is unplaced.
DEFAULT_WORKING_TIERS: list[dict] = [
    {"id": "tier-s", "label": "S-Tier", "dimension_keys": []},
    {"id": "tier-a", "label": "A-Tier", "dimension_keys": []},
    {"id": "tier-b", "label": "B-Tier", "dimension_keys": []},
]

# The synthesized Ignore zone's identity (display only; never persisted).
IGNORE_TIER_ID = "ignore"
IGNORE_TIER_LABEL = "Ignore"


def default_tier_layout() -> list[dict]:
    """The opening *stored* layout: the empty working tiers, no Ignore tier.

    "Ignored" is the absence of a placement, so an opening board (everything
    unplaced) is just the empty working tiers; ``weights_from_tiers`` then falls
    back to uniform, giving the equal-weight baseline until the committee tiers.
    """
    return [dict(t, dimension_keys=list(t["dimension_keys"])) for t in DEFAULT_WORKING_TIERS]


def stored_tiers(run: ScreeningRun) -> list[dict]:
    """The run's stored *working* tiers (no Ignore zone), or the default when unset.

    Only working tiers are ever stored (``set_tiers`` strips the Ignore zone the UI
    sends; ``create_run`` writes working tiers only), so this is a plain read.
    """
    stored = (run.criteria or {}).get("tiers")
    if stored:
        return [dict(t) for t in stored]
    return default_tier_layout() if current_pattern_report(run) is not None else []


def display_tiers(run: ScreeningRun) -> list[dict]:
    """The working tiers plus a synthesized Ignore zone holding every dimension not
    placed in a working tier — the shape the tier-list UI renders. The Ignore zone
    is derived here, never stored, so 'ignored' always means exactly 'unplaced'.
    """
    working = stored_tiers(run)
    report = current_pattern_report(run)
    if report is None:
        return working
    placed = {key for t in working for key in t.get("dimension_keys", [])}
    ignored = [d.key for d in report.dimensions if d.key not in placed]
    return working + [
        {"id": IGNORE_TIER_ID, "label": IGNORE_TIER_LABEL, "dimension_keys": ignored, "ignore": True}
    ]


def carry_forward_layout(
    *,
    new_report: PoolPatternReport,
    old_tiers: list[dict],
    new_to_old: dict[str, str],
) -> tuple[list[dict], list[str]]:
    """Build the new run's *working*-tier layout by carrying old placements forward.

    ``old_tiers`` is the prior run's working tiers (no Ignore zone — that's derived).
    Re-uses the committee's prior structure (their renamed/added/reordered tiers),
    placing each new dimension into the working tier its matched old dimension
    occupied. Three cases per new dimension:
      - matched a prior dimension in a working tier → carried into that tier;
      - matched a prior dimension that was in Ignore → left unplaced (the
        committee's "ignore" decision carries forward), and NOT flagged new —
        they already weighed in on it;
      - no match to any prior dimension → left unplaced AND flagged new, so the
        committee triages a dimension they have never seen.
    "Unplaced" means weight 0 ("ignored"), so it cannot influence the ranking
    until the committee acts. The key distinction is *matched vs. not* — not which
    tier the match landed in — so a prior-Ignored survivor is never mislabeled new.

    Returns ``(working_tiers, new_dimension_keys)`` where ``new_dimension_keys`` is
    only the genuinely-new (unmatched) keys, for "new" badging in the UI. Falls
    back to the empty default working tiers when there is no prior layout (a first run).
    """
    if not old_tiers:
        return default_tier_layout(), []

    # old_key -> the id of the working tier it was in (so we can place new dims there).
    old_key_to_tier: dict[str, str] = {}
    for tier in old_tiers:
        for key in tier.get("dimension_keys", []):
            old_key_to_tier[key] = tier["id"]

    # Clone the old working-tier structure, emptied of dimensions.
    layout: list[dict] = [
        {"id": tier["id"], "label": tier["label"], "dimension_keys": []}
        for tier in old_tiers
    ]
    by_id = {tier["id"]: tier for tier in layout}

    new_dimension_keys: list[str] = []
    for dim in new_report.dimensions:
        old_key = new_to_old.get(dim.key)
        if old_key is None:
            # No match to ANY prior dimension: genuinely new. Unplaced (ignored
            # by absence) and flagged so the committee triages it.
            new_dimension_keys.append(dim.key)
            continue
        # Matched a prior dimension. If that dimension was in a working tier,
        # carry the placement forward. If it was in Ignore (not in the map, since
        # Ignore isn't stored), leave this one unplaced too — carrying the
        # committee's "ignore" decision forward — but it is NOT new: they already
        # weighed in on it, so it gets no badge.
        target = old_key_to_tier.get(old_key)
        if target is not None and target in by_id:
            by_id[target]["dimension_keys"].append(dim.key)

    return layout, new_dimension_keys


def weights_from_tiers(
    dimension_keys: list[str], tier_layout: list[dict]
) -> dict[str, float]:
    """Derive per-dimension weights from a tier layout — the pure heart of M9.

    The layout holds only *working* tiers (most→least important); "ignored" is the
    absence of a placement, not a stored tier. Working tiers are weighted by
    position, top to bottom: with ``n`` tiers the top gets ``n``, the next ``n-1`` …
    down to ``1``; equal within a tier. A dimension in **no** tier has weight ``0``
    — it does not influence fit. Only keys in ``dimension_keys`` are returned, so a
    stale tier entry naming a dropped dimension is ignored.

    If *no* dimension ends up with a positive weight — nothing placed (the opening
    default, where every dimension is "ignored" by absence), or no tiers at all —
    fit would be zero for everyone and the ranking would collapse to an arbitrary
    order. The committee can't have meant "rank on nothing," so this falls back to
    uniform weights: an empty board ranks on the equal-weight baseline until
    something is tiered.
    """
    keys = set(dimension_keys)
    tier_count = len(tier_layout)

    placed: dict[str, float] = {}
    for rank, tier in enumerate(tier_layout):
        weight = float(tier_count - rank)
        for key in tier.get("dimension_keys", []):
            if key in keys:
                placed[key] = weight

    # Unplaced = ignored, weight 0. (A dimension the committee never moved out of
    # the Ignore zone, or one just added.)
    weights = {key: placed.get(key, 0.0) for key in dimension_keys}

    # Nothing carries positive weight (empty board, or no tiers): fall back to
    # uniform so the opening ranking is the equal-weight baseline rather than an
    # all-zero, arbitrarily-ordered collapse.
    if not any(w > 0.0 for w in weights.values()):
        return {key: 1.0 for key in dimension_keys}

    return weights


def set_tiers(
    db: Session, run: ScreeningRun, tier_layout: list[dict]
) -> ScreeningRun:
    """Persist a new tier layout and the weights derived from it.

    The layout is the source of truth; ``criteria.weights`` is recomputed from it
    so the ranking engine (which reads ``weights``) stays untouched. Validates that
    every placed key is a real dimension of this run.

    Only *working* tiers are stored — the UI sends an Ignore zone for display, but
    "ignored" is the absence of a placement, so the incoming Ignore tier is dropped
    before persisting. There is therefore no "must have an Ignore tier" invariant:
    an empty layout simply means everything is ignored (weight 0 → uniform fallback).
    """
    report = current_pattern_report(run)
    valid_keys = {d.key for d in report.dimensions} if report is not None else set()
    for tier in tier_layout:
        for key in tier.get("dimension_keys", []):
            if key not in valid_keys:
                raise ValueError(f"Unknown dimension key in tier layout: {key!r}")

    working = [
        {"id": t["id"], "label": t["label"], "dimension_keys": list(t.get("dimension_keys", []))}
        for t in tier_layout
        if not t.get("ignore")
    ]
    weights = weights_from_tiers(sorted(valid_keys), working)
    # criteria is a JSON column; reassign a new dict so SQLAlchemy sees the change.
    run.criteria = {**(run.criteria or {}), "tiers": working, "weights": weights}
    db.commit()
    db.refresh(run)
    return run
