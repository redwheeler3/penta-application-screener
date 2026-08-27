"""Per-member ranking tiers, proposals, carry-forward, and review flags."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.schemas import PoolDimensionReport
from app.db.models import Analysis, MemberRanking, User
from app.services.ranking.dimensions import current_dimension_report


def get_or_create_member_ranking(
    db: Session, analysis: Analysis, user: User
) -> MemberRanking:
    """This member's view of ``analysis``. Named ``get_or_create`` because it WRITES when
    absent: a member who didn't trigger the Rank has no view of the new analysis until they
    open it, so the first read materializes one — seeded by carrying their prior tiers forward
    (the same all-history carry-forward a re-rank uses). A brand-new member (no prior tiering
    anywhere) gets the default all-Ignore layout.
    """
    existing = db.scalar(
        select(MemberRanking).where(
            MemberRanking.analysis_id == analysis.id,
            MemberRanking.user_id == user.id,
        )
    )
    if existing is not None:
        return existing

    report = current_dimension_report(analysis)
    scaffold, most_recent = tier_history(db, user)
    if report is not None and scaffold:
        immediately_prior = _immediately_prior_keys(db, user, before_analysis_id=analysis.id)
        layout, flagged = carry_forward_layout(
            new_report=report,
            scaffold_tiers=scaffold,
            most_recent_tier_by_key=most_recent,
            immediately_prior_keys=immediately_prior,
        )
    else:
        layout, flagged = default_tier_layout(), []

    member_ranking = MemberRanking(
        analysis_id=analysis.id,
        user_id=user.id,
        run_state={
            "tiers": layout,
            "new_dimension_keys": flagged,
            "proposed_dimensions": [],
        },
    )
    db.add(member_ranking)
    db.commit()
    db.refresh(member_ranking)
    return member_ranking


def dimension_weights(member_ranking: MemberRanking) -> dict[str, float]:
    """The member's per-dimension weights — a complete map, DERIVED from their tier layout
    (never stored; tiers are the source of truth). Empty before any dimensions exist.
    Reads the shared dimensions off ``member_ranking.analysis`` and the tiers off the member's
    own view."""
    report = current_dimension_report(member_ranking.analysis)
    if report is None:
        return {}
    return weights_from_tiers([d.key for d in report.dimensions], stored_tiers(member_ranking))



def kept_keys(member_ranking: MemberRanking) -> list[str]:
    """Dimension keys this member has KEPT — every key they placed in a working
    (non-Ignore) tier. A kept axis is guaranteed to survive the next Rank (injected
    at decomposition as MUST-survive); Ignore is the only "fair game to drop/re-carve"
    bucket. There is no separate stored set: tier placement IS the keep signal, so
    this derives from the member's tiers and can never drift out of sync with them
    (``carry_forward_layout`` already carries placements across re-runs and merges).

    Only keys still present in the shared report are returned (a stale tier entry
    naming a dropped dimension is ignored). Ignore is synthesized from what's unplaced,
    so it is never in ``stored_tiers`` — reading the stored working tiers already
    excludes it.
    """
    report = current_dimension_report(member_ranking.analysis)
    valid = {d.key for d in report.dimensions} if report is not None else set()
    placed = {key for tier in stored_tiers(member_ranking) for key in tier.get("dimension_keys", [])}
    return sorted(placed & valid)


def proposed_dimensions(member_ranking: MemberRanking) -> list[str]:
    """Pending free-text axes this member proposed, awaiting the next Rank to realize
    them. Cleared once a run consumes them (they become real dimensions).
    """
    return list((member_ranking.run_state or {}).get("proposed_dimensions", []))



def set_proposals(
    db: Session,
    member_ranking: MemberRanking,
    *,
    proposed_dimensions: list[str] | None = None,
) -> MemberRanking:
    """Persist this member's pending free-text proposals between runs — the axes they
    want the next Rank to ground in the pool. A no-op when ``None`` is passed. (Keeping an
    existing axis across re-runs is tier placement, not a stored seed; see ``kept_keys``.)
    """
    if proposed_dimensions is None:
        return member_ranking
    # Trim blanks/whitespace and dedupe while preserving order.
    seen: set[str] = set()
    cleaned: list[str] = []
    for text in proposed_dimensions:
        t = text.strip()
        if t and t not in seen:
            seen.add(t)
            cleaned.append(t)
    member_ranking.run_state = {**(member_ranking.run_state or {}), "proposed_dimensions": cleaned}
    db.commit()
    db.refresh(member_ranking)
    return member_ranking


# The opening working tiers (most→least important), empty so every dimension is
# "ignored" by absence until the committee tiers it. The Ignore zone is never
# stored; it's synthesized for display from whatever is unplaced.
DEFAULT_WORKING_TIERS: list[dict] = [
    {"id": "tier-s", "label": "Critical", "dimension_keys": []},
    {"id": "tier-a", "label": "Important", "dimension_keys": []},
    {"id": "tier-b", "label": "Minor", "dimension_keys": []},
]

# The synthesized Ignore zone's identity (display only; never persisted).
IGNORE_TIER_ID = "ignore"
IGNORE_TIER_LABEL = "Ignore"


def default_tier_layout() -> list[dict]:
    """The opening *stored* layout: the empty working tiers, no Ignore tier.
    ``weights_from_tiers`` then falls back to the uniform equal-weight baseline.
    """
    return [dict(t, dimension_keys=list(t["dimension_keys"])) for t in DEFAULT_WORKING_TIERS]


def stored_tiers(member_ranking: MemberRanking) -> list[dict]:
    """This member's stored *working* tiers (no Ignore zone), or the default when unset."""
    stored = (member_ranking.run_state or {}).get("tiers")
    if stored:
        return [dict(t) for t in stored]
    return default_tier_layout() if current_dimension_report(member_ranking.analysis) is not None else []


def display_tiers(member_ranking: MemberRanking) -> list[dict]:
    """This member's working tiers plus a synthesized Ignore zone of every unplaced
    dimension — the shape the tier-list UI renders. The Ignore zone is derived, never stored.
    """
    working = stored_tiers(member_ranking)
    report = current_dimension_report(member_ranking.analysis)
    if report is None:
        return working
    placed = {key for t in working for key in t.get("dimension_keys", [])}
    ignored = [d.key for d in report.dimensions if d.key not in placed]
    return [*working, {"id": IGNORE_TIER_ID, "label": IGNORE_TIER_LABEL, "dimension_keys": ignored, "ignore": True}]


def tier_history(db: Session, user: User) -> tuple[list[dict], dict[str, str]]:
    """One member's tier intent across ALL their rankings, for carrying placements forward.

    Tiering is per-member, so this walks THIS member's ``MemberRanking`` rows (newest analysis
    first), reading their tiers from each and dimension presence from the shared ``analysis``.

    Returns ``(scaffold_tiers, most_recent_tier_by_key)``:
      - ``scaffold_tiers`` — the member's most recent working-tier *structure* (ids +
        labels, no dimensions), used as the board to place onto. Empty if they have none.
      - ``most_recent_tier_by_key`` — key → the tier id it was MOST RECENTLY in, across
        this member's rankings. **Ignore is a first-class tier here** (id ``IGNORE_TIER_ID``):
        a key that was present in an analysis's report but in no working tier of the member's
        ranking was Ignored by them there, so it maps to ``"ignore"``. Because we scan
        newest-first, a recent Ignore correctly overrides an older working placement — dragging
        a key to Ignore is a durable decision, not the absence of one. A key genuinely absent
        from an analysis's report (gone from the pool) records nothing there, so its last real
        appearance still wins — that is the revival path.

    This is the all-history basis for ``carry_forward_layout``: each key restores to
    the tier it was most-recently in (Ignore included), so an untouched Ignored key
    stays in Ignore across re-ranks. ``"ignore"`` is not a working scaffold id, so a
    key mapping to it simply stays unplaced (lands in the derived Ignore zone) — never
    injected into a working tier or the ``kept_keys`` set.
    """
    rankings = db.scalars(
        select(MemberRanking)
        .where(MemberRanking.user_id == user.id)
        .join(Analysis)
        .order_by(Analysis.id.desc())
    ).all()
    scaffold: list[dict] = []
    most_recent_tier_by_key: dict[str, str] = {}
    # Newest analysis first: the first tier we see for a key is its most-recent one.
    # Scaffold from the member's newest ranking that has working tiers.
    for ranking in rankings:
        tiers = stored_tiers(ranking)
        if not scaffold and tiers:
            scaffold = [
                {"id": t["id"], "label": t["label"], "dimension_keys": []} for t in tiers
            ]
        placed: set[str] = set()
        for tier in tiers:
            for key in tier.get("dimension_keys", []):
                most_recent_tier_by_key.setdefault(key, tier["id"])
                placed.add(key)
        # A key present in this analysis's report but in no working tier of the member's
        # ranking was Ignored by them here. Record it so a recent Ignore beats an older
        # working placement.
        report = current_dimension_report(ranking.analysis)
        if report is not None:
            for dim in report.dimensions:
                if dim.key not in placed:
                    most_recent_tier_by_key.setdefault(dim.key, IGNORE_TIER_ID)
    return scaffold, most_recent_tier_by_key


def _immediately_prior_keys(db: Session, user: User, *, before_analysis_id: int) -> set[str]:
    """The dimension keys of this member's ranking on the analysis IMMEDIATELY BEFORE
    ``before_analysis_id`` — the ones continuous in their view (never flagged). Empty if
    they had no prior ranking. Reads the report off that prior analysis; the member had a
    view of it (that's what "prior ranking" means)."""
    prior = db.scalar(
        select(MemberRanking)
        .where(MemberRanking.user_id == user.id, MemberRanking.analysis_id < before_analysis_id)
        .join(Analysis)
        .order_by(Analysis.id.desc())
        .limit(1)
    )
    if prior is None:
        return set()
    report = current_dimension_report(prior.analysis)
    return {d.key for d in report.dimensions} if report is not None else set()


def revived_flag_keys(db: Session, member_ranking: MemberRanking) -> list[str]:
    """Of this member ranking's flagged keys (``new_dimension_keys`` — the one unacknowledged
    triage set), those that appeared in an earlier analysis get the "revived" label (seen
    before, dropped for at least the immediately-prior analysis, now back); the rest are
    genuinely "new" (never seen in any prior analysis).

    The label is derived at read time; both kinds share one stored flagged set.
    New = flagged − revived, computed by the caller or frontend.

    "Seen before" is a fact about the shared dimension history (the analyses), not about this
    member's tiering — a key counts as seen once any earlier analysis discovered it. A flagged
    key is by construction absent from the immediately-prior analysis, so "seen in any analysis
    before this one" means a revived key genuinely SKIPPED at least the last one. A dimension
    that persists run-to-run is never flagged, so never labelled revived.
    """
    flagged = set((member_ranking.run_state or {}).get("new_dimension_keys", []))
    if not flagged:
        return []
    earlier = db.scalars(
        select(Analysis)
        .where(Analysis.id < member_ranking.analysis_id)
        .order_by(Analysis.id.desc())
    ).all()
    seen_before: set[str] = set()
    for prior in earlier:
        report = current_dimension_report(prior)
        if report is not None:
            seen_before.update(d.key for d in report.dimensions)
    return sorted(flagged & seen_before)


def requested_flag_keys(member_ranking: MemberRanking) -> list[str]:
    """This member's committee-requested dimensions still awaiting their acknowledgement — the
    keys with ``from_committee_request`` set on the shared analysis (a member proposed this axis
    for the Rank that produced it; see ``enforce_committee_requests``) minus any this member has
    dismissed.

    Provenance, not triage: unlike ``new_dimension_keys`` this flag is authoritative on the
    shared report (recomputed per analysis, cleared on the next Rank), so the "still flagged"
    set is derived — the report flag minus this member's stored ``acknowledged_requested_keys``
    dismissal set, the same shape the badge ✕ uses for new/revived. The dismissal is per-member;
    the request provenance is shared. Empty when the analysis had no proposal.
    """
    report = current_dimension_report(member_ranking.analysis)
    if report is None:
        return []
    acknowledged = set((member_ranking.run_state or {}).get("acknowledged_requested_keys", []))
    return sorted(
        d.key for d in report.dimensions if d.from_committee_request and d.key not in acknowledged
    )


def carry_forward_layout(
    *,
    new_report: PoolDimensionReport,
    scaffold_tiers: list[dict],
    most_recent_tier_by_key: dict[str, str],
    immediately_prior_keys: set[str],
) -> tuple[list[dict], list[str]]:
    """Build the new run's working-tier layout by carrying committee intent forward
    across ALL runs (see ``tier_history`` for the inputs).

    Runs *after* ``adopt_matched_keys``, so a matched dimension already shares its
    prior key — carry-forward is pure key equality. Per new dimension, restore its
    most-recent tier (see ``tier_history`` — Ignore is a first-class tier there):
      - most-recent tier was a working tier → placed there;
      - most-recent tier was Ignore (present-but-unplaced in that run) → unplaced. This
        is a *durable* ignore: dragging a key to Ignore beats an older working placement,
        so an untouched Ignored key stays in Ignore across re-ranks;
      - key never seen in any run → unplaced.

    Two flag states ride on the returned ``flagged_keys`` (the single mutable triage
    set the UI badges — stored as ``new_dimension_keys``). A key is flagged when it
    needs the committee's attention, which is a *presence-gap* fact: flag it when it is
    **absent from the immediately-prior run but
    present now** — whether it was never seen (a genuinely new axis) OR seen in an
    earlier run, dropped, and now back (revived). A key that was in the immediately-
    prior run is continuous in the committee's view → never flagged, however it
    re-surfaced. The new-vs-revived *label* (amber vs. blue) is derived at read time
    from history (see ``revived_flag_keys``); this function only decides *whether* to flag.
    A revived key is BOTH placed (its prior tier restored) AND flagged.

    Returns ``(working_tiers, flagged_keys)``. Falls back to the empty default tiers
    when no prior run placed anything.
    """
    if not scaffold_tiers:
        return default_tier_layout(), []

    layout: list[dict] = [
        {"id": t["id"], "label": t["label"], "dimension_keys": []} for t in scaffold_tiers
    ]
    by_id = {tier["id"]: tier for tier in layout}

    flagged_keys: list[str] = []
    for dim in new_report.dimensions:
        # Restore the key's most-recent tier. Only working-tier ids are in `by_id`, so a
        # key whose most-recent tier was Ignore (id "ignore") — or one never seen — finds
        # no match and stays unplaced, landing in the derived Ignore zone.
        target = most_recent_tier_by_key.get(dim.key)
        if target is not None and target in by_id:
            by_id[target]["dimension_keys"].append(dim.key)
        # Flag on the presence gap: absent from the immediately-prior run but here now.
        # Covers both never-seen (new) and dropped-then-back (revived); a key present
        # in the prior run is continuous and never flagged.
        if dim.key not in immediately_prior_keys:
            flagged_keys.append(dim.key)

    return layout, flagged_keys


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
        return dict.fromkeys(dimension_keys, 1.0)

    return weights


def set_tiers(
    db: Session,
    member_ranking: MemberRanking,
    tier_layout: list[dict],
    acknowledged_keys: list[str] | None = None,
    acknowledged_requested_keys: list[str] | None = None,
) -> MemberRanking:
    """Persist this member's new tier layout (weights are derived from it, never stored).

    Validates that every placed key is a real dimension of the shared analysis. Only working
    tiers are stored — the UI's Ignore zone is dropped before persisting (an empty layout just
    means everything is ignored → uniform fallback).

    ``acknowledged_requested_keys`` dismiss the "requested" provenance pill (badge ✕). Unlike
    new/revived, the requested flag is authoritative on the shared report and is NOT cleared by
    moving the chip — it is provenance, so only an explicit dismissal (or the next Rank clearing
    the underlying flag) removes it. The dismissals accumulate per-member in
    ``acknowledged_requested_keys``; ``requested_flag_keys`` subtracts them.

    ``new_dimension_keys`` (the one unacknowledged-flag set — "new" OR "revived") clears on the
    SAME rule as the requested pill, for consistency across all three badges: a flag clears ONLY
    on an explicit acknowledgement (badge ✕ / "mark all reviewed") — NOT on moving the chip to a
    tier — and otherwise rides until the next Rank recomputes the flagged set. Dragging a flagged
    chip into a working tier keeps its badge (it is now weighted AND still flagged as
    newly-arrived); the member dismisses it with the ✕ when they have taken it in. Only
    re-discovery / carry-forward re-flags.
    """
    report = current_dimension_report(member_ranking.analysis)
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

    # Recompute the still-flagged set: drop only the explicitly-acknowledged keys. Moving
    # a chip no longer clears its flag (consistent with the requested pill) — the badge
    # rides until the ✕ or the next Rank. Keys still valid on this analysis only.
    acknowledged = set(acknowledged_keys or ())
    prior_flagged = (member_ranking.run_state or {}).get("new_dimension_keys", [])
    surviving = [
        k for k in prior_flagged
        if k in valid_keys and k not in acknowledged
    ]

    # Accumulate requested-pill dismissals (explicit ✕ only). Union with what's already
    # stored so a later save doesn't resurrect an earlier dismissal; keep only keys still
    # requested on the shared report (a dismissal for a non-requested key is meaningless).
    prior_ack_requested = set((member_ranking.run_state or {}).get("acknowledged_requested_keys", []))
    requested_keys = {d.key for d in report.dimensions if d.from_committee_request} if report else set()
    ack_requested = sorted(
        (prior_ack_requested | set(acknowledged_requested_keys or ())) & requested_keys
    )

    # run_state is a JSON column; reassign a new dict so SQLAlchemy sees the change.
    # proposed_dimensions is preserved; weights are derived from tiers, never stored.
    member_ranking.run_state = {
        **(member_ranking.run_state or {}),
        "tiers": working,
        "new_dimension_keys": surviving,
        "acknowledged_requested_keys": ack_requested,
    }
    db.commit()
    db.refresh(member_ranking)
    return member_ranking
