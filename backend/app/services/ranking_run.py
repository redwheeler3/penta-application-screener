"""Ranking-run persistence.

A ``RankingRun`` holds the discovered ``PoolDimensionReport``. Per-candidate
scores are NOT stored here — they live in ``ApplicationAIResult`` rows under
``kind = "dimension_scoring:<dimension_key>"``, so a dimension's **key** joins
back to a candidate's score. A matched dimension is replaced wholesale by its
prior self (key + text) via ``adopt_matched_keys`` across a re-rank, so its tier
placement, cached score, AND the wording that score was computed against all carry
forward together (see SPEC "Pattern Discovery And Dimension Scoring"). "The current
run" is the most recent one.

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

from app.ai.schemas import PoolDimension, PoolDimensionReport
from app.db.models import Application, ApplicationStatus, RankingRun
from app.schemas.settings import AppSettings


def pool_fingerprint(db: Session) -> str:
    """A stable hash of the eligible pool's inputs.

    Built from the sorted ``raw_row_hash`` of every eligible application, which
    captures the three pool changes that should trigger a re-rank: a new applicant,
    an edited application (its hash changes), and an eligibility flip. Status source
    and AI outputs are excluded — they don't change what the pool says.

    This is the *pool* half of the rank-inputs fingerprint; ``rank_inputs_fingerprint``
    combines it with the prompt + model identity of the passes a Rank runs.
    """
    hashes = db.scalars(
        select(Application.raw_row_hash)
        .where(Application.status == ApplicationStatus.ELIGIBLE)
        .order_by(Application.raw_row_hash)
    ).all()
    basis = "\n".join(hashes)
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


def rank_inputs_fingerprint(db: Session, settings: AppSettings) -> str:
    """A stable hash of everything a Rank's output depends on, used to detect when a
    re-rank would produce something different — which drives the "Rank out of date"
    badge.

    Combines the pool fingerprint with the **prompt identity and model** of every
    pass the Rank chain runs (essays → discovery + match + reconcile → scoring). So a
    re-rank is flagged current only when the pool, all five prompts, AND all five
    rank-chain models are unchanged since the run was created — editing any rank-chain
    prompt or switching a model now correctly shows Rank as stale, not just a pool
    change. (screening is the separate Screen step, not part of Rank, so excluded.)

    Prompt versions are imported lazily: the AI passes import this module, so a
    top-level import would be circular (matches the existing local-import pattern in
    ``estimate_match``).
    """
    from app.ai.dimension_matching import PROMPT_VERSION as MATCH_V
    from app.ai.dimension_reconcile import PROMPT_VERSION as RECONCILE_V
    from app.ai.dimension_scoring import PROMPT_VERSION as SCORING_V
    from app.ai.essay_analysis import PROMPT_VERSION as ESSAY_V
    from app.ai.pattern_discovery import PROMPT_VERSION as DISCOVERY_V

    parts = [
        pool_fingerprint(db),
        f"essay:{ESSAY_V}",
        f"discovery:{DISCOVERY_V}",
        f"match:{MATCH_V}",
        f"reconcile:{RECONCILE_V}",
        f"scoring:{SCORING_V}",
        # The model of every rank-chain pass — one per pass now, so a change to any
        # of them ambers Rank. Screening's model is deliberately absent: it's the
        # separate Screen step, not part of Rank (same reason its prompt is absent).
        f"essay_model:{settings.ai.essay_analysis_model}",
        f"discovery_model:{settings.ai.discovery_model}",
        f"match_model:{settings.ai.match_model}",
        f"reconcile_model:{settings.ai.reconcile_model}",
        f"scoring_model:{settings.ai.dimension_scoring_model}",
    ]
    basis = "\n".join(parts)
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


def adopt_matched_keys(
    report: PoolDimensionReport,
    new_to_old: dict[str, str],
    prior: PoolDimensionReport | None,
) -> PoolDimensionReport:
    """Replace a freshly-discovered dimension that matched a prior one with the prior
    dimension **wholesale** — prior key AND prior text (name, definition,
    why_it_differentiates) — discarding the fresh wording.

    A matched dimension reuses its cached score (the score cache is keyed by key), and
    that score was computed by the model reading the PRIOR definition. So the prior
    text is the only wording consistent with the reused score: swapping in freshly
    re-discovered wording would show the committee a number scored against a
    definition it no longer sees. Score and text must move together, so a match
    freezes both. (Discovery's fresh re-read is genuinely more current, but that only
    matters for a dimension we re-score — an unmatched one, below.)

    An unmatched dimension keeps its fresh key and fresh text (→ cache miss → scored
    fresh, so text and score are aligned by construction). Guard: never adopt a key
    already taken by another dimension here (would duplicate); rare, only if the LLM
    re-coins an old key for a different concept.
    """
    prior_by_key = {d.key: d for d in prior.dimensions} if prior is not None else {}
    taken: set[str] = set()
    dims = []
    for dim in report.dimensions:
        old_key = new_to_old.get(dim.key)
        matched = old_key is not None and old_key not in taken and old_key in prior_by_key
        if matched:
            # Adopt the prior dimension's key AND text (they pair with the cached
            # score), but keep the FRESH from_committee_request flag — that is this
            # run's provenance (did the committee ask for this axis now?), not part of
            # the scored concept, and it drives auto-favouriting in create_run.
            adopted = prior_by_key[old_key].model_copy(
                update={"from_committee_request": dim.from_committee_request}
            )
        else:
            adopted = dim  # unmatched → keep fresh key + text (scored fresh below)
        taken.add(adopted.key)
        dims.append(adopted)
    return report.model_copy(update={"dimensions": dims})


def revive_dimensions(
    report: PoolDimensionReport,
    revive_keys: list[str],
    prior: PoolDimensionReport | None,
) -> PoolDimensionReport:
    """Re-enter each reconcile-revived dropped prior into the report, by its
    historical key + text (from ``prior`` = the all-history report the reconcile pass
    judged against).

    Runs *after* ``adopt_matched_keys``, so ``report`` already holds every matched +
    freshly-discovered dimension. Revived keys are the dropped priors the reconcile
    pass said the pool still varies on; adding them back under their historical key
    means their cached scores are reused (score cache is keyed by key) and their tier
    placement carries forward — identical to any other carried key. A revive_key
    already present (defensive; the dropped set excludes matched keys) is skipped, so
    no duplicate.
    """
    if not revive_keys or prior is None:
        return report
    prior_by_key = {d.key: d for d in prior.dimensions}
    existing = {d.key for d in report.dimensions}
    revived = [
        prior_by_key[k] for k in revive_keys if k in prior_by_key and k not in existing
    ]
    if not revived:
        return report
    return report.model_copy(update={"dimensions": [*report.dimensions, *revived]})


def reconcile_audit_payload(
    ballot: list[dict], revive_keys: list[str], narrative: str | None = None
) -> dict | None:
    """Shape the reconcile pass's full ballot for storage on the run, or None when the
    pass didn't run (first run / nothing dropped — an empty ballot).

    Stores every verdict (both revivals and rejections, per SPEC RQ8b), the offered
    and recovered counts, so ``reconcile_audit_view`` can derive the recovery rate —
    the over-recovery smell. A zero-recovery run still writes a row (healthy signal).

    ``narrative`` is the model's free-text reasoning from the pass, persisted so the
    Insights tab can render it later (the live stream is gone by then). Mirrors the
    match pass's stored ``match_narrative``.
    """
    if not ballot:
        return None
    return {
        "verdicts": ballot,  # [{old_key, revive, reasoning}]
        "offered_count": len(ballot),
        "recovered_count": len(revive_keys),
        "narrative": narrative,
    }


def create_run(
    db: Session,
    *,
    report: PoolDimensionReport,
    settings: AppSettings,
    model_id: str,
    narrative: str | None,
    discovery_cost_usd: float,
    match_cost_usd: float = 0.0,
    reconcile_cost_usd: float = 0.0,
    name: str = "Ranking run",
    tier_layout: list[dict] | None = None,
    new_dimension_keys: list[str] | None = None,
    prior_favourited_keys: list[str] | None = None,
    match_audit: dict | None = None,
    reconcile_audit: dict | None = None,
    fan_out_audit: dict | None = None,
    decompose_audit: dict | None = None,
    decompose_cost_usd: float = 0.0,
) -> RankingRun:
    """Persist a freshly discovered pattern report as a new ranking run.

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
    run = RankingRun(
        name=name,
        status="patterns_discovered",
        criteria={
            "dimension_report": report.model_dump(mode="json"),
            # Everything this run's ranking depends on — pool + rank-chain prompt and
            # model identity. The next Rank compares it to flag the run "out of date"
            # when the pool, any rank-chain prompt, or a model has changed.
            "rank_inputs_fingerprint": rank_inputs_fingerprint(db, settings),
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
            # Discovery and match are separate Bedrock calls (different models), stored
            # separately so the cost report can attribute each. match_cost is 0 on a
            # first run (no match pass ran).
            "discovery_cost_usd": round(discovery_cost_usd, 6),
            "match_cost_usd": round(match_cost_usd, 6),
            # Reconcile is a third Bedrock call (dropped-dimension second look), priced
            # separately. 0 on a first run / when nothing dropped (pass skipped).
            "reconcile_cost_usd": round(reconcile_cost_usd, 6),
            # Carry-forward audit: raw pre-adopt discovery dims + the match map +
            # match narrative, so a re-rank's "what changed" is inspectable (genuine
            # re-discovery vs. match over-matching). None on a first run (no match).
            "match_audit": match_audit,
            # Reconcile audit: the full ballot (verdict + reasoning per dropped prior)
            # + offered/recovered counts, so over-recovery is inspectable. None when
            # the pass didn't run (first run / nothing dropped).
            "reconcile_audit": reconcile_audit,
            # Fan-out audit (SPEC "Fan-Out Redesign"): the K raw discovery reports this
            # run produced, before decomposition settled them into one set. None on runs
            # written before fan-out landed (single-discovery runs).
            "fan_out_audit": fan_out_audit,
            # Decompose audit (SPEC "Fan-Out Redesign", Phase 4a): per settled axis, the
            # source_keys it absorbed + the merge/keep reasoning (the Insights surface +
            # the D9 committee-request trail). None on runs written before decomposition.
            "decompose_audit": decompose_audit,
            # Decomposition is its own Bedrock call (settle the K reports into one set),
            # priced separately so the cost report can attribute it.
            "decompose_cost_usd": round(decompose_cost_usd, 6),
        },
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def get_current_run(db: Session) -> RankingRun | None:
    """The most recent ranking run, or None if discovery has never run."""
    return db.scalar(select(RankingRun).order_by(RankingRun.id.desc()).limit(1))


def all_known_dimensions(db: Session) -> PoolDimensionReport | None:
    """Every distinct dimension ever discovered, one entry per key (most recent
    definition kept), as a synthetic report for the identity-match pass.

    The match pass matches a fresh discovery against this whole history, not just the
    last run — so a concept that fell out of a run and re-surfaced is recognized and
    RE-ADOPTS its existing key, instead of minting a new one. That keeps the distinct
    key count converging on the true number of concepts (~20-25) rather than growing a
    few per run, and (because the score cache is keyed by dimension key) lets those
    re-adopted keys reuse their cached scores. See SPEC "Matching scope".

    Returns None when no run has ever discovered dimensions.
    """
    # Newest run first, so the first time we see a key we take its latest definition.
    runs = db.scalars(select(RankingRun).order_by(RankingRun.id.desc())).all()
    latest_by_key: dict[str, PoolDimension] = {}
    for run in runs:
        report = current_dimension_report(run)
        if report is None:
            continue
        for dim in report.dimensions:
            if dim.key not in latest_by_key:
                latest_by_key[dim.key] = dim
    if not latest_by_key:
        return None
    return PoolDimensionReport(
        summary="All dimensions discovered across prior runs (identity-match history).",
        dimensions=list(latest_by_key.values()),
    )


def ranking_is_current(db: Session, run: RankingRun | None, settings: AppSettings) -> bool:
    """True when ``run``'s stored rank-inputs fingerprint matches the inputs now —
    i.e. the pool, every rank-chain prompt, and both models are unchanged, so a
    re-rank would be a no-op. Drives the "Rank out of date" badge.

    False if there is no run, or the run predates rank-inputs fingerprinting (older
    runs stored only ``pool_fingerprint``; treat them as stale so the first re-rank
    re-stamps them with the richer fingerprint).
    """
    if run is None:
        return False
    stored = (run.criteria or {}).get("rank_inputs_fingerprint")
    if not stored:
        return False
    return stored == rank_inputs_fingerprint(db, settings)


def current_dimension_report(run: RankingRun) -> PoolDimensionReport | None:
    """Parse the stored ``PoolDimensionReport`` from a run's criteria, if present."""
    payload = (run.criteria or {}).get("dimension_report")
    if payload is None:
        return None
    return PoolDimensionReport.model_validate(payload)


def dimension_weights(run: RankingRun) -> dict[str, float]:
    """The run's per-dimension weights (always a complete map, derived from tiers)."""
    return {k: float(v) for k, v in ((run.criteria or {}).get("weights") or {}).items()}


def favourited_keys(run: RankingRun) -> list[str]:
    """Dimension keys the committee favourited — kept (re-fed to discovery) across
    re-runs. Only keys still present in the run's report are returned.
    """
    report = current_dimension_report(run)
    valid = {d.key for d in report.dimensions} if report is not None else set()
    return [k for k in (run.criteria or {}).get("favourited_keys", []) if k in valid]


def proposed_dimensions(run: RankingRun) -> list[str]:
    """Pending free-text axes a member proposed, awaiting the next Rank to realize
    them. Cleared once a run consumes them (they become real dimensions).
    """
    return list((run.criteria or {}).get("proposed_dimensions", []))


def match_audit_view(run: RankingRun) -> dict | None:
    """The run's carry-forward audit, shaped for the trace viewer, or None when the
    run predates match-audit capture (older runs stored no audit).

    The stored audit (``criteria.match_audit``) records what discovery *actually*
    emitted before ``adopt_matched_keys`` rewrote matched keys, plus the new→old map
    and the match narrative. This adds the derived **carry-forward rate** (matched /
    discovered) — a persistently near-100% rate is the smell that the match pass is
    over-matching. ``carry_forward_rate`` is None on a first run, where there were no
    prior dimensions to match against and the rate is undefined (not zero).
    """
    audit = (run.criteria or {}).get("match_audit")
    if not audit:
        return None
    discovered = audit.get("raw_discovery_dimensions", [])
    new_to_old = audit.get("new_to_old", {}) or {}
    prior_names = audit.get("prior_dimension_names", {}) or {}
    matched = len(new_to_old)
    is_first_run = not audit.get("prior_dimension_count", 0)
    # Resolve each matched new-key to the prior dimension it adopted: its prior key and
    # (when known — older audits lack the names map) the prior user-facing name. Lets
    # the viewer show the prior title alongside the key, mirroring the discovered column.
    new_to_old_named = {
        new_key: {"key": old_key, "name": prior_names.get(old_key)}
        for new_key, old_key in new_to_old.items()
    }
    return {
        "raw_discovery_dimensions": discovered,
        "new_to_old": new_to_old_named,
        "match_narrative": audit.get("match_narrative"),
        "prior_dimension_count": audit.get("prior_dimension_count", 0),
        "discovered_count": len(discovered),
        "matched_count": matched,
        "new_count": len(discovered) - matched,
        # Fraction of newly-discovered dimensions the match pass mapped onto a prior
        # one. None (not 0.0) on a first run — nothing to match against.
        "carry_forward_rate": (
            None if is_first_run or not discovered else round(matched / len(discovered), 4)
        ),
    }


def reconcile_audit_view(run: RankingRun) -> dict | None:
    """The run's reconcile audit — the dropped-dimension second look — shaped for the
    trace viewer, or None when the reconcile pass did not run (first run / nothing
    dropped / run predates the capture).

    The stored audit (``criteria.reconcile_audit``) is the full ballot: a verdict +
    reasoning per dropped prior. This adds the derived **recovery rate** (recovered /
    offered) — the over-recovery smell (RQ8): a persistently high rate means reconcile
    is reviving too readily under the rationalization pressure the prompt guards
    against. A zero-recovery run (rate 0.0) is the healthy signal, and still returns a
    view (the pass ran); only a skipped pass returns None.
    """
    audit = (run.criteria or {}).get("reconcile_audit")
    if not audit:
        return None
    offered = audit.get("offered_count", 0)
    recovered = audit.get("recovered_count", 0)
    return {
        "verdicts": audit.get("verdicts", []),  # [{old_key, revive, reasoning}]
        "offered_count": offered,
        "recovered_count": recovered,
        # Fraction of dropped priors reconcile revived. None only if somehow nothing
        # was offered (defensive; a stored audit always has offered > 0).
        "recovery_rate": round(recovered / offered, 4) if offered else None,
        # The model's free-text reasoning (markdown), for the Insights panel. None on
        # runs written before narrative capture.
        "narrative": audit.get("narrative"),
    }


def decompose_audit_view(run: RankingRun) -> dict | None:
    """The run's decompose audit — how the K fan-out reports were settled into one set —
    shaped for the trace viewer, or None on runs that predate decomposition (single-
    discovery runs have no ``criteria.decompose_audit``).

    The stored audit (built by ``dimension_decompose.decompose_audit_payload``) is already
    view-shaped: settled axes with source_keys + decision reasoning, the input/settled
    counts, and the D9 ``folded_requests`` trail. This is a thin pass-through with
    defaults, mirroring the other ``*_audit_view`` accessors so the router stays uniform.
    """
    audit = (run.criteria or {}).get("decompose_audit")
    if not audit:
        return None
    return {
        "input_report_count": audit.get("input_report_count", 0),
        "input_dimension_count": audit.get("input_dimension_count", 0),
        "settled_count": audit.get("settled_count", 0),
        "merge_count": audit.get("merge_count", 0),
        "settled": audit.get("settled", []),
        "folded_requests": audit.get("folded_requests", []),
        "narrative": audit.get("narrative"),
    }


def set_seeds(
    db: Session,
    run: RankingRun,
    *,
    favourited_keys: list[str] | None = None,
    proposed_dimensions: list[str] | None = None,
) -> RankingRun:
    """Persist the committee's discovery seeds between runs: which existing
    dimensions are favourited and which free-text axes are proposed. Each arg is
    applied only when provided, so the caller can update one without touching the
    other. Favourites are validated against the run's real dimension keys.
    """
    criteria = dict(run.criteria or {})
    if favourited_keys is not None:
        report = current_dimension_report(run)
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


def stored_tiers(run: RankingRun) -> list[dict]:
    """The run's stored *working* tiers (no Ignore zone), or the default when unset."""
    stored = (run.criteria or {}).get("tiers")
    if stored:
        return [dict(t) for t in stored]
    return default_tier_layout() if current_dimension_report(run) is not None else []


def display_tiers(run: RankingRun) -> list[dict]:
    """The working tiers plus a synthesized Ignore zone of every unplaced dimension
    — the shape the tier-list UI renders. The Ignore zone is derived, never stored.
    """
    working = stored_tiers(run)
    report = current_dimension_report(run)
    if report is None:
        return working
    placed = {key for t in working for key in t.get("dimension_keys", [])}
    ignored = [d.key for d in report.dimensions if d.key not in placed]
    return [*working, {"id": IGNORE_TIER_ID, "label": IGNORE_TIER_LABEL, "dimension_keys": ignored, "ignore": True}]


def tier_history(db: Session) -> tuple[list[dict], dict[str, str], set[str]]:
    """Committee tier intent across ALL runs, for carrying placements forward.

    Returns ``(scaffold_tiers, most_recent_tier_by_key, known_keys)``:
      - ``scaffold_tiers`` — the most recent run's working-tier *structure* (ids +
        labels, no dimensions), used as the board to place onto. Empty if no runs.
      - ``most_recent_tier_by_key`` — key → the working-tier id it was MOST RECENTLY
        placed in, across all runs. A key the committee last left in Ignore is absent
        (Ignore is the absence of a placement), so it restores to unplaced.
      - ``known_keys`` — every key that has appeared in any run. Absence ⇒ genuinely
        new (gets the "New" badge); presence ⇒ the committee has seen it, so never
        badged new even if it fell out for a few runs.

    This is the all-history basis for ``carry_forward_layout``: a placement is durable
    committee intent that doesn't expire when a dimension drops out and re-surfaces, so
    we honor the LAST tier they put each key in, from whichever run that was.
    """
    runs = db.scalars(select(RankingRun).order_by(RankingRun.id.desc())).all()
    scaffold: list[dict] = []
    most_recent_tier_by_key: dict[str, str] = {}
    known_keys: set[str] = set()
    # Newest run first: the first placement we see for a key is its most-recent one.
    # Scaffold from the newest run that has working tiers.
    for run in runs:
        report = current_dimension_report(run)
        if report is not None:
            known_keys.update(d.key for d in report.dimensions)
        tiers = stored_tiers(run)
        if not scaffold and tiers:
            scaffold = [
                {"id": t["id"], "label": t["label"], "dimension_keys": []} for t in tiers
            ]
        for tier in tiers:
            for key in tier.get("dimension_keys", []):
                most_recent_tier_by_key.setdefault(key, tier["id"])
    return scaffold, most_recent_tier_by_key, known_keys


def revived_flag_keys(db: Session, run: RankingRun) -> list[str]:
    """Of ``run``'s flagged keys (``new_dimension_keys`` — the one unacknowledged
    triage set), those that appeared in an earlier run get the "revived" label (seen
    before, dropped for at least the immediately-prior run, now back); the rest are
    genuinely "new" (never seen in any prior run).

    Label only, derived at read time — both kinds share the one stored flagged set,
    so there is no second field to keep in sync (SPEC "badge is presence-driven,
    reuses the one existing flags set"). New = flagged − revived, computed by the
    caller/frontend.

    Note the gap semantics: a flagged key is by construction absent from the
    immediately-prior run (``carry_forward_layout`` only flags absent-from-prior
    keys), so "seen in any run before this one" is equivalent to "seen in a run
    *before the immediately-prior one*" for a flagged key — a revived key genuinely
    SKIPPED at least the last run. A dimension that persists run-to-run is never
    flagged, so never labelled revived.
    """
    flagged = set((run.criteria or {}).get("new_dimension_keys", []))
    if not flagged:
        return []
    earlier = db.scalars(
        select(RankingRun).where(RankingRun.id < run.id).order_by(RankingRun.id.desc())
    ).all()
    seen_before: set[str] = set()
    for prior in earlier:
        report = current_dimension_report(prior)
        if report is not None:
            seen_before.update(d.key for d in report.dimensions)
    return sorted(flagged & seen_before)


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
    prior key — carry-forward is pure key equality. Per new dimension:
      - key most-recently placed in a working tier (any prior run) → placed there;
      - key seen before but last left in Ignore → unplaced (the committee already
        weighed it — a durable "ignore");
      - key never seen in any run → unplaced.

    Two flag states ride on the returned ``flagged_keys`` (the single mutable triage
    set the UI badges — stored as ``new_dimension_keys``). A key is flagged when it
    needs the committee's attention, which is a *presence-gap* fact (SPEC "badge is
    presence-driven"): flag it when it is **absent from the immediately-prior run but
    present now** — whether it was never seen (a genuinely new axis) OR seen in an
    earlier run, dropped, and now back (revived). A key that was in the immediately-
    prior run is continuous in the committee's view → never flagged, however it
    re-surfaced. The new-vs-revived *label* (amber vs. blue) is derived at read time
    from history (see ``flag_labels``); this function only decides *whether* to flag.
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
        # Restore the most-recent working-tier placement for any seen-before key
        # (a never-seen key has none, so it stays unplaced).
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
    run: RankingRun,
    tier_layout: list[dict],
    acknowledged_keys: list[str] | None = None,
) -> RankingRun:
    """Persist a new tier layout and the weights derived from it.

    Validates that every placed key is a real dimension of this run. Only working
    tiers are stored — the UI's Ignore zone is dropped before persisting (an empty
    layout just means everything is ignored → uniform fallback).

    ``new_dimension_keys`` (the one unacknowledged-flag set — "new" OR "revived") is
    recomputed by ONE uniform rule: **a flag clears on a member action — an explicit
    acknowledgement (badge ✕ / "mark all reviewed"), or the member MOVING the chip
    (its placement differs from what was stored) — but never by carry-forward's own
    auto-placement.** That single rule yields both behaviors for free:
      - a *new* key starts unplaced, so the only way it becomes placed is a member
        drag → cleared (identical to the prior "placement clears" behavior);
      - a *revived* key starts auto-placed (its prior tier restored), so leaving it
        put is not a move → it stays flagged until the member explicitly reviews or
        re-places it (the SPEC RQ4 safeguard: a revived dim silently at weight keeps
        its badge). Only re-discovery re-flags.
    Comparing against the *stored* placement (not "is it placed?") is what makes
    auto-placement not self-clear, with no new-vs-revived branch here.
    """
    report = current_dimension_report(run)
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

    # Recompute the still-flagged set: drop any acknowledged, or moved from where it
    # was stored (None = unplaced). Auto-placement leaves stored==incoming, so it
    # doesn't clear; a genuine member move does.
    def _placement(tiers: list[dict]) -> dict[str, str]:
        return {key: t["id"] for t in tiers for key in t.get("dimension_keys", [])}

    stored_placement = _placement(stored_tiers(run))
    incoming_placement = _placement(working)
    acknowledged = set(acknowledged_keys or ())
    prior_flagged = (run.criteria or {}).get("new_dimension_keys", [])
    surviving = [
        k for k in prior_flagged
        if k in valid_keys
        and k not in acknowledged
        and incoming_placement.get(k) == stored_placement.get(k)  # not moved
    ]

    # criteria is a JSON column; reassign a new dict so SQLAlchemy sees the change.
    run.criteria = {
        **(run.criteria or {}),
        "tiers": working,
        "weights": weights,
        "new_dimension_keys": surviving,
    }
    db.commit()
    db.refresh(run)
    return run
