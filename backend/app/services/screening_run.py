"""Screening-run persistence.

A ``ScreeningRun`` holds the discovered ``PoolPatternReport``. Per-candidate
scores are NOT stored here — they live in ``ApplicationAIResult`` rows under
``kind = "dimension_scoring:<dimension_key>"``, so a dimension's **key** joins
back to a candidate's score. A matched dimension's key is rewritten to its prior
key (``adopt_matched_keys``) across a re-rank, so its tier placement and cached
score both carry forward by key alone (see SPEC "Pattern Discovery And Dimension
Scoring"). "The current run" is the most recent one.

Weights are derived from the tier layout, never proposed by the AI: the run stores
``criteria.tiers`` (working tiers only) and recomputes ``criteria.weights`` from
it. A fresh run opens with empty tiers → uniform equal-weight baseline until the
committee tiers. Discovering the axes is the AI's job; deciding what matters is the
committee's.
"""

from __future__ import annotations

import hashlib

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.schemas import PoolPatternReport
from app.db.models import Application, ApplicationStatus, ScreeningRun


def pool_fingerprint(db: Session) -> str:
    """A stable hash of the eligible pool's inputs, used to block a no-op Rank.

    Built from the sorted ``raw_row_hash`` of every eligible application, which
    captures the three things that should trigger a re-rank: a new applicant, an
    edited application (its hash changes), and an eligibility flip. Status source
    and AI outputs are excluded — they don't change what the pool says.
    """
    hashes = db.scalars(
        select(Application.raw_row_hash)
        .where(Application.status == ApplicationStatus.ELIGIBLE)
        .order_by(Application.raw_row_hash)
    ).all()
    basis = "\n".join(hashes)
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


def adopt_matched_keys(
    report: PoolPatternReport, new_to_old: dict[str, str]
) -> PoolPatternReport:
    """Rewrite a freshly-discovered dimension's **key** to its matched prior key,
    keeping the new content (name, definition, why_it_differentiates).

    The key is a stable cross-run identity, not committee-facing text. Adopting the
    prior key carries everything keyed on it — tier placements AND the score cache —
    forward by key alone. The new descriptions are kept because discovery just
    re-read this pool, so its wording is current; only the identifier is borrowed.

    An unmatched dimension keeps its fresh key (→ cache miss → scored). Guard: never
    adopt a key already taken by another dimension here (would duplicate); rare,
    only if the LLM re-coins an old key for a different concept.
    """
    taken: set[str] = set()
    dims = []
    for dim in report.dimensions:
        old_key = new_to_old.get(dim.key)
        key = old_key if (old_key is not None and old_key not in taken) else dim.key
        taken.add(key)
        dims.append(dim.model_copy(update={"key": key}))
    return report.model_copy(update={"dimensions": dims})


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
    prior_favourited_keys: list[str] | None = None,
    match_audit: dict | None = None,
) -> ScreeningRun:
    """Persist a freshly discovered pattern report as a new screening run.

    ``tier_layout`` carries prior placements forward across a re-rank (see
    ``carry_forward_layout``); omitted → the default all-Ignore layout. Either way
    the run stores tiers explicitly and derives ``weights`` from them.
    ``new_dimension_keys`` are the unmatched new dimensions to flag in the UI; empty
    on a first run.

    ``favourited_keys`` (the durable "keep across re-runs" set) is the union of
    ``prior_favourited_keys`` carried forward (matched dimensions kept their prior
    key via ``adopt_matched_keys``, so this is plain key equality) and every
    dimension the model flagged ``from_committee_request`` (a proposed/favourited
    axis it just realized) — pruned to keys that actually exist in this report.
    Pending ``proposed_dimensions`` are consumed by the run, so the new run stores
    an empty list (they are now real dimensions).
    """
    layout = tier_layout if tier_layout is not None else default_tier_layout()
    dimension_keys = [d.key for d in report.dimensions]
    valid_keys = set(dimension_keys)
    favourited = {k for k in (prior_favourited_keys or []) if k in valid_keys}
    favourited |= {d.key for d in report.dimensions if d.from_committee_request}
    run = ScreeningRun(
        name=name,
        status="patterns_discovered",
        criteria={
            "pattern_report": report.model_dump(mode="json"),
            # Lets the next Rank detect an unchanged pool and skip a no-op re-run.
            "pool_fingerprint": pool_fingerprint(db),
            # Tiers are the source of truth; weights are derived from them. A fresh
            # all-Ignore board derives uniform weights (the equal-weight baseline).
            "tiers": layout,
            "weights": weights_from_tiers(dimension_keys, layout),
            "new_dimension_keys": new_dimension_keys or [],
            # Durable "keep these axes across re-runs"; carried forward + auto-added
            # for axes the committee requested. Proposals are consumed, so empty here.
            "favourited_keys": sorted(favourited),
            "proposed_dimensions": [],
            "discovery_model_id": model_id,
            "discovery_narrative": narrative,
            "discovery_cost_usd": round(cost_usd, 6),
            # Carry-forward audit: raw pre-adopt discovery dims + the match map +
            # match narrative, so a re-rank's "what changed" is inspectable (genuine
            # re-discovery vs. match over-matching). None on a first run (no match).
            "match_audit": match_audit,
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
    """True when ``run``'s stored ``pool_fingerprint`` matches the pool now (the
    no-op Rank gate). False if there is no run, or the run predates fingerprinting.
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
    """The run's per-dimension weights (always a complete map, derived from tiers)."""
    return {k: float(v) for k, v in ((run.criteria or {}).get("weights") or {}).items()}


def favourited_keys(run: ScreeningRun) -> list[str]:
    """Dimension keys the committee favourited — kept (re-fed to discovery) across
    re-runs. Only keys still present in the run's report are returned.
    """
    report = current_pattern_report(run)
    valid = {d.key for d in report.dimensions} if report is not None else set()
    return [k for k in (run.criteria or {}).get("favourited_keys", []) if k in valid]


def proposed_dimensions(run: ScreeningRun) -> list[str]:
    """Pending free-text axes a member proposed, awaiting the next Rank to realize
    them. Cleared once a run consumes them (they become real dimensions).
    """
    return list((run.criteria or {}).get("proposed_dimensions", []))


def set_seeds(
    db: Session,
    run: ScreeningRun,
    *,
    favourited_keys: list[str] | None = None,
    proposed_dimensions: list[str] | None = None,
) -> ScreeningRun:
    """Persist the committee's discovery seeds between runs: which existing
    dimensions are favourited and which free-text axes are proposed. Each arg is
    applied only when provided, so the caller can update one without touching the
    other. Favourites are validated against the run's real dimension keys.
    """
    criteria = dict(run.criteria or {})
    if favourited_keys is not None:
        report = current_pattern_report(run)
        valid = {d.key for d in report.dimensions} if report is not None else set()
        criteria["favourited_keys"] = sorted({k for k in favourited_keys if k in valid})
    if proposed_dimensions is not None:
        # Trim blanks/whitespace and dedupe while preserving order.
        seen: set[str] = set()
        cleaned: list[str] = []
        for text in proposed_dimensions:
            t = text.strip()
            if t and t not in seen:
                seen.add(t)
                cleaned.append(t)
        criteria["proposed_dimensions"] = cleaned
    run.criteria = criteria  # reassign so SQLAlchemy tracks the JSON change
    db.commit()
    db.refresh(run)
    return run


# The opening working tiers (most→least important), empty so every dimension is
# "ignored" by absence until the committee tiers it. The Ignore zone is never
# stored; it's synthesized for display from whatever is unplaced.
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
    ``weights_from_tiers`` then falls back to the uniform equal-weight baseline.
    """
    return [dict(t, dimension_keys=list(t["dimension_keys"])) for t in DEFAULT_WORKING_TIERS]


def stored_tiers(run: ScreeningRun) -> list[dict]:
    """The run's stored *working* tiers (no Ignore zone), or the default when unset."""
    stored = (run.criteria or {}).get("tiers")
    if stored:
        return [dict(t) for t in stored]
    return default_tier_layout() if current_pattern_report(run) is not None else []


def display_tiers(run: ScreeningRun) -> list[dict]:
    """The working tiers plus a synthesized Ignore zone of every unplaced dimension
    — the shape the tier-list UI renders. The Ignore zone is derived, never stored.
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
    prior_keys: set[str],
) -> tuple[list[dict], list[str]]:
    """Build the new run's working-tier layout by carrying old placements forward.

    Runs *after* ``adopt_matched_keys``, so a matched dimension already shares its
    prior key — carry-forward is pure key equality. ``prior_keys`` is every key the
    prior run had (working *and* Ignored), which distinguishes "matched" from "new".
    Three cases per new dimension:
      - key in a prior working tier → carried into that tier;
      - key was a prior dimension that sat in Ignore → left unplaced (carrying the
        committee's "ignore" forward), NOT flagged new — they already weighed in;
      - key not a prior key at all → left unplaced AND flagged new to triage.
    The distinction is *was it a prior dimension*, so a prior-Ignored survivor is
    never mislabeled new.

    Returns ``(working_tiers, new_dimension_keys)`` — the latter only the genuinely
    new keys. Falls back to the empty default tiers on a first run.
    """
    if not old_tiers:
        return default_tier_layout(), []

    # key -> the id of the working tier it was in (so we can place it there again).
    key_to_tier: dict[str, str] = {}
    for tier in old_tiers:
        for key in tier.get("dimension_keys", []):
            key_to_tier[key] = tier["id"]

    # Clone the old working-tier structure, emptied of dimensions.
    layout: list[dict] = [
        {"id": tier["id"], "label": tier["label"], "dimension_keys": []}
        for tier in old_tiers
    ]
    by_id = {tier["id"]: tier for tier in layout}

    new_dimension_keys: list[str] = []
    for dim in new_report.dimensions:
        if dim.key not in prior_keys:
            # Genuinely new: unplaced and flagged for triage.
            new_dimension_keys.append(dim.key)
            continue
        # A prior dimension (key adopted on match). Carry its working-tier placement
        # forward; if it was in Ignore, leave it unplaced — no badge.
        target = key_to_tier.get(dim.key)
        if target is not None and target in by_id:
            by_id[target]["dimension_keys"].append(dim.key)

    return layout, new_dimension_keys


def weights_from_tiers(
    dimension_keys: list[str], tier_layout: list[dict]
) -> dict[str, float]:
    """Derive per-dimension weights from a tier layout.

    Working tiers are weighted by position top→bottom: with ``n`` tiers the top
    gets ``n``, the next ``n-1`` … down to ``1``; equal within a tier. A dimension
    in no tier has weight ``0``. Only keys in ``dimension_keys`` are returned, so a
    stale entry naming a dropped dimension is ignored.

    If no dimension carries positive weight (empty board, or no tiers), fit would be
    zero for everyone and the ranking would collapse to an arbitrary order — so this
    falls back to uniform weights (the equal-weight baseline) until something is
    tiered.
    """
    keys = set(dimension_keys)
    tier_count = len(tier_layout)

    placed: dict[str, float] = {}
    for rank, tier in enumerate(tier_layout):
        weight = float(tier_count - rank)
        for key in tier.get("dimension_keys", []):
            if key in keys:
                placed[key] = weight

    # Unplaced = ignored, weight 0.
    weights = {key: placed.get(key, 0.0) for key in dimension_keys}

    # Nothing weighted (empty board or no tiers): fall back to uniform.
    if not any(w > 0.0 for w in weights.values()):
        return {key: 1.0 for key in dimension_keys}

    return weights


def set_tiers(
    db: Session,
    run: ScreeningRun,
    tier_layout: list[dict],
    acknowledged_keys: list[str] | None = None,
) -> ScreeningRun:
    """Persist a new tier layout and the weights derived from it.

    Validates that every placed key is a real dimension of this run. Only working
    tiers are stored — the UI's Ignore zone is dropped before persisting (an empty
    layout just means everything is ignored → uniform fallback).

    ``new_dimension_keys`` is recomputed: a dimension stays flagged "new" only while
    still unplaced AND not in ``acknowledged_keys``. So a badge clears two ways —
    placing the dimension in a working tier, or explicit acknowledgement (badge ✕ /
    "mark all reviewed"). Only re-discovery re-flags.
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

    # Recompute the still-"new" set: drop any acknowledged or now placed in a tier.
    placed = {key for t in working for key in t.get("dimension_keys", [])}
    acknowledged = set(acknowledged_keys or ())
    prior_new = (run.criteria or {}).get("new_dimension_keys", [])
    surviving_new = [
        k for k in prior_new
        if k in valid_keys and k not in acknowledged and k not in placed
    ]

    # criteria is a JSON column; reassign a new dict so SQLAlchemy sees the change.
    run.criteria = {
        **(run.criteria or {}),
        "tiers": working,
        "weights": weights,
        "new_dimension_keys": surviving_new,
    }
    db.commit()
    db.refresh(run)
    return run
