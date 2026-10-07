"""Persistence and input provenance for committee-wide ranking analyses."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.schemas import PoolDimension, PoolDimensionReport
from app.db.models import (
    Analysis,
    AnalysisAudit,
    DimensionAlias,
    MemberRanking,
    User,
)
from app.schemas.settings import AppSettings
from app.services.applications.scope import opening_ai_applications
from app.services.ranking.dimensions import alias_map, current_dimension_report
from app.services.ranking.identity import flatten_merges
from app.services.ranking.member_state import (
    IGNORE_TIER_ID,
    default_tier_layout,
    lock_member_state,
    proposed_dimensions,
    reconcile_consolidated_members,
    tier_history,
)


def create_analysis(
    db: Session,
    *,
    user: User,
    opening_id: int,
    report: PoolDimensionReport,
    inputs_fingerprint: str,
    narrative: str | None,
    tier_layout: list[dict] | None = None,
    new_dimension_keys: list[str] | None = None,
    match_audit: dict | None = None,
    fan_out_audit: dict | None = None,
    decompose_audit: dict | None = None,
    configuration: dict | None = None,
) -> Analysis:
    """Persist a freshly discovered pattern report as a new shared ``Analysis`` and seed the
    triggering member's ``MemberRanking`` view of it.

    ``tier_layout``/``new_dimension_keys`` are that member's carried-forward placements and
    triage flags (see ``carry_forward_layout``); omitted → the default all-Ignore layout. They
    are per-member, so they live on the new ``MemberRanking``, not the shared analysis. Other
    members get their own ``MemberRanking`` lazily (carried forward from their own prior view)
    the first time they read this analysis — see ``get_member_ranking``.

    There is no stored "kept" set: an axis is kept iff the member placed it in a working
    (non-Ignore) tier, and ``tier_layout`` already carries those placements forward across
    re-runs. ``kept_keys`` derives the set from the tiers at read time, so it can't drift.
    The run consumes pending ``proposed_dimensions``, so the new view starts with an empty list.
    """
    layout = tier_layout if tier_layout is not None else default_tier_layout()
    applications = opening_ai_applications(db, opening_id)
    analysis = Analysis(
        opening_id=opening_id,
        synthetic_data=bool(applications) and all(
            application.synthetic_data for application in applications
        ),
        dimension_report=report.model_dump(mode="json"),
        # Captured before discovery, so edits made during the run keep it out of date.
        rank_inputs_fingerprint=inputs_fingerprint,
        # The AI-legibility trail lives in the 1:1 child so the hot read path stays lean.
        #   - discovery_narrative: the discovery pass's streamed reasoning.
        #   - match: raw pre-adopt discovery dims + the match map + narrative, so a re-rank's
        #     "what changed" is inspectable (re-discovery vs. over-matching). None on a first run.
        #   - fan_out: the K raw discovery reports before decomposition settled them. None on
        #     analyses written before fan-out landed.
        #   - decompose: per settled axis, the source_keys it absorbed + merge/keep reasoning
        #     (Observability surface + the committee-request trail). None before decomposition.
        #   - consolidate: filled later by apply_consolidation (post-score); None until then.
        audit=AnalysisAudit(
            discovery_narrative=narrative,
            match=match_audit,
            fan_out=({**(fan_out_audit or {}), "configuration": configuration}
                     if configuration is not None else fan_out_audit),
            decompose=decompose_audit,
        ),
    )
    db.add(analysis)
    db.flush()  # assign analysis.id for the MemberRanking FK
    # The triggering member's view. Tiers are the source of truth for weights (derived, never
    # stored). A fresh all-Ignore board stays unranked. Proposals are consumed by this
    # run, so empty here.
    db.add(
        MemberRanking(
            analysis_id=analysis.id,
            user_id=user.id,
            run_state={
                "tiers": layout,
                "new_dimension_keys": new_dimension_keys or [],
                "proposed_dimensions": [],
            },
        )
    )
    db.commit()
    db.refresh(analysis)
    return analysis


def apply_consolidation(
    db: Session,
    analysis: Analysis,
    member_ranking: MemberRanking,
    *,
    merges: dict[str, str],
    audit: list[dict],
    narrative: str | None,
    settings: AppSettings,
    configuration: dict | None = None,
) -> Analysis:
    """Fold confirmed duplicate keys into their canonical key on an already-persisted
    analysis during post-score consolidation.

    Consolidation is committee-wide: the model call ran once over the shared pool, so the
    merge is a fact about the shared ``analysis``. Two kinds of write happen here:
      - **Shared** (on ``analysis``): persist a ``DimensionAlias`` row per merge (so future
        matches adopt the canonical key), drop the loser from ``dimension_report``, and record
        the ``consolidate`` audit. These are true for everyone.
      - **Per-member tier transfer**: reconcile every existing personal view atomically;
        future views inherit canonicalized personal history. Each survivor takes that
        member's own highest-priority placement, never another member's judgment.

    A merge can also heal a CROSS-RUN fork, where the surviving ``keep`` is a PRIOR-analysis
    key that never appeared in THIS one (only the newer ``drop`` twin surfaced; the
    definition-match pass missed the fork, but score-vector correlation caught it). There the
    winner is *not* already in the report, so dropping the loser alone would delete the axis —
    instead surface the canonical key itself: bring back its frozen MINT record and restore the
    working tier the member last placed it in (keys must never be mixed up: cache identity and
    tier/flag history both ride on the exact key). Weights are re-derived from the collapsed
    tiers (never stored). Always records the ``consolidate`` audit (even with zero merges — the
    pass ran), for Observability. The pass's cost lands in the run cost ledger, not here.
    """
    lock_member_state(db, member_ranking)
    db.refresh(analysis)
    report_json = dict(analysis.dimension_report or {})

    # A single run's merges can form a chain: if C→B correlates higher than B→A, the
    # confirm loop emits {C: B, B: A}. Flatten every drop to its TERMINAL survivor
    # ({C: A, B: A}) so aliases point straight at the winner and every by-value lookup
    # below (tier-placement transfer especially) lands on a key that still exists, not a
    # mid-chain key that was itself dropped.
    known_aliases = alias_map(db)
    resolved = flatten_merges({**known_aliases, **merges})
    merges = {drop: resolved[drop] for drop in merges}

    # A confirmed concept match cannot replace scores under another frozen wording.
    # Check terminal survivors against the same current cache grid used by scoring.
    if merges:
        from app.ai.dimension_scoring import (
            applications_to_score,
            kind_for_dimension,
            plan_dimension_scoring,
        )
        from app.ai.result_selection import select_results

        history = all_known_dimensions(db)
        mint_by_key = {dimension.key: dimension for dimension in history.dimensions} if history else {}
        survivors = PoolDimensionReport(dimensions=[mint_by_key[key]
            for key in dict.fromkeys(merges.values()) if key in mint_by_key])
        plan = plan_dimension_scoring(db, applications=applications_to_score(db, analysis.opening_id),
            report=survivors, settings=settings)
        unsafe = {dimension.key for applicant in plan.applicants for dimension in applicant.dimensions_to_score}
        unsafe.update(key for key in merges.values() if key not in mint_by_key)
        frozen_fields = {"name", "definition", "high_end", "low_end"}
        for dimension in report_json.get("dimensions", []):
            key = dimension["key"]
            if key in merges.values() and key in mint_by_key:
                if any(dimension.get(field) != getattr(mint_by_key[key], field) for field in frozen_fields):
                    unsafe.add(key)
        deferred = {drop for drop, keep in merges.items() if keep in unsafe}
        applied_audit = []
        for pair in audit:
            recorded_pair = dict(pair)
            if pair.get("merged"):
                if pair.get("drop") in deferred:
                    recorded_pair.update(merged=False, deferred_reason=(
                        "Merge deferred: the terminal survivor lacks frozen wording or complete current scores."))
                elif pair.get("drop") in merges:
                    recorded_pair["applied_keep"] = merges[pair["drop"]]
            applied_audit.append(recorded_pair)
        audit = applied_audit
        merges = {drop: keep for drop, keep in merges.items() if drop not in deferred}
        # Readers consume selected references, not every reusable cache row. Adopt
        # these already-validated scores in the same transaction as their report keys.
        survivor_kinds = {kind_for_dimension(key) for key in merges.values()}
        select_results(db, [reference for reference in plan.cached_references if reference[1] in survivor_kinds])

    if merges:
        # An alias may already exist: matching is high-bar, so a merged key can be
        # re-minted by discovery and re-nominated on a later run. Upsert rather than
        # blind-insert — a second confirm of the same merge must be a no-op, not a
        # UNIQUE-constraint crash that rolls back the whole run.
        existing = {
            a.alias_key: a
            for a in db.scalars(
                select(DimensionAlias).where(DimensionAlias.alias_key.in_(list(merges)))
            )
        }
        for drop_key, keep_key in merges.items():
            reason = next(
                (a.get("reason") for a in audit if a.get("drop") == drop_key), None
            )
            row = existing.get(drop_key)
            if row is None:
                db.add(
                    DimensionAlias(
                        alias_key=drop_key,
                        canonical_key=keep_key,
                        reason=reason,
                    )
                )
            else:
                # Keep the alias pointing at the current canonical key + latest reason.
                row.canonical_key = keep_key
                row.reason = reason

        report_dims = [
            d for d in report_json.get("dimensions", []) if d.get("key") not in merges
        ]

        # Cross-run fork heal: a surviving ``keep`` that isn't in this analysis's report is a
        # PRIOR-analysis key this one never re-discovered on its own — only the newer ``drop``
        # twin surfaced, the definition-match pass missed the fork, and score-vector
        # correlation caught it here. Dropping the loser alone would delete the axis, so
        # surface the canonical key itself: bring back its FROZEN MINT record (never the
        # drop's re-worded text — cache identity rides on the exact key), and restore the
        # working tier the member last placed it in (same revival path a normally
        # re-surfacing key takes, via this member's tier_history most-recent placement).
        present = {d.get("key") for d in report_dims}
        resurfaced = [k for k in dict.fromkeys(merges.values()) if k not in present]
        if resurfaced:
            report_dims.extend(mint_by_key[k].model_dump(mode="json") for k in resurfaced)
        report_json["dimensions"] = report_dims
        analysis.dimension_report = report_json
        db.flush()  # Personal history must see the final report and persisted aliases.
        reconcile_consolidated_members(db, analysis, merges=merges, resurfaced=resurfaced)

    # Persisted for EVERY run the pass ran on, merges or not. Each pair row carries both
    # judged definitions (definition_keep/definition_drop), so this audit is the durable,
    # self-contained record of a consolidation decision — critical on a MERGE, where the
    # dropped dimension has just been removed from dimension_report above and would
    # otherwise leave no definition behind to evaluate the merge against. The applied
    # merge map is NOT stored here — it's dimension_aliases (the merge-truth); the view
    # derives it from the merged pairs.
    consolidate_audit = {"pairs": audit, "narrative": narrative, "configuration": configuration}
    if analysis.audit is None:
        analysis.audit = AnalysisAudit(consolidate=consolidate_audit)
    else:
        analysis.audit.consolidate = consolidate_audit

    db.commit()
    db.refresh(analysis)
    return analysis


def get_current_analysis(db: Session, opening_id: int) -> Analysis | None:
    """The most recent shared analysis, or None if discovery has never run."""
    return db.scalar(
        select(Analysis)
        .where(Analysis.opening_id == opening_id)
        .order_by(Analysis.id.desc())
        .limit(1)
    )


def get_latest_analysis(db: Session) -> Analysis | None:
    """Most recent analysis across openings for global admin/eval tooling."""
    return db.scalar(select(Analysis).order_by(Analysis.id.desc()).limit(1))




def key_history(db: Session) -> tuple[dict[str, int], dict[str, str], dict[str, str]]:
    """For consolidation: (canonical_rank, definitions, names) over every key ever discovered.

    ``canonical_rank[key]`` = the id of the EARLIEST run the key appeared in — so a
    lower rank means older, and consolidation keeps the older key on a merge (maximizing
    cache carry-forward). ``definitions[key]`` = the key's MINT definition (its earliest
    appearance), for the confirm prompt to judge a nominated pair. ``names[key]`` = the
    key's MINT user-facing name, for the audit to label the pair with names, not just
    keys. One pass, oldest first.

    Definition (and name) is the mint, not the newest, for the same key/text immutability
    reason as ``all_known_dimensions``: a key's cached scores were computed against the
    text it was minted with, so the confirm call must judge that text — not a later
    re-worded version that would divorce the definition from the scores it reasons about.
    Rank and definition therefore both come from the SAME (earliest) run, so a key's judged
    wording never drifts off the scores it reasons about.
    """
    analyses = db.scalars(select(Analysis).order_by(Analysis.id.asc())).all()
    rank: dict[str, int] = {}
    definitions: dict[str, str] = {}
    names: dict[str, str] = {}
    for analysis in analyses:
        report = current_dimension_report(analysis)
        if report is None:
            continue
        for dim in report.dimensions:
            rank.setdefault(dim.key, analysis.id)  # first (oldest) analysis wins the rank
            definitions.setdefault(dim.key, dim.definition)  # and the mint definition
            names.setdefault(dim.key, dim.name)  # and the mint name
    return rank, definitions, names


def all_known_dimensions(db: Session) -> PoolDimensionReport | None:
    """Every distinct concept ever discovered, one entry per key, each carrying the text
    it was MINTED with — a synthetic report for the identity-match pass.

    The match pass matches a fresh discovery against this whole history, not just the
    last run — so a concept that fell out of a run and re-surfaced is recognized and
    re-adopts its existing key instead of minting a new one. That keeps the distinct
    key count converging on the true number of concepts (~20-25) rather than growing a
    few per run and lets those keys reuse cached scores.

    **Key/text immutability invariant.** A key's descriptive text (definition, poles,
    why-it-differentiates) is FROZEN when the key is minted and never changes, because
    the score cache is keyed by key and every cached score was computed against that
    frozen text. Different text ⇒ a different key. So this returns each key's *own mint*
    definition (its earliest appearance), and a retired alias key NEVER donates its
    wording to the canonical key it merged into: the canonical's text and cached scores
    must remain aligned.

    Consolidation aliases are still resolved to their canonical key, so a key a prior run
    retired as a duplicate never re-enters the match target set — but only the canonical's
    OWN entry supplies text; the alias contributes nothing. Returns None when no run has
    ever discovered dimensions.
    """
    aliases = alias_map(db)
    # Oldest analysis first, so the first time we see a key is its MINT — the frozen text
    # its cached scores were computed against. A later analysis's re-worded re-discovery of
    # the same key is ignored (the invariant: text can't drift under a key).
    analyses = db.scalars(select(Analysis).order_by(Analysis.id.asc())).all()
    minted_by_key: dict[str, PoolDimension] = {}
    for analysis in analyses:
        report = current_dimension_report(analysis)
        if report is None:
            continue
        for dim in report.dimensions:
            canonical = aliases.get(dim.key, dim.key)
            # Only a key's OWN appearance defines its text — never an alias donation.
            # (canonical is the older key, minted before any alias key appears, so its
            # own mint is always seen first; an alias-key dim is skipped entirely.)
            if canonical != dim.key or canonical in minted_by_key:
                continue
            minted_by_key[canonical] = dim
    if not minted_by_key:
        return None
    return PoolDimensionReport(dimensions=list(minted_by_key.values()))


def has_known_dimensions(db: Session) -> bool:
    """Check matching's global history without materializing analysis audit blobs."""
    aliases = alias_map(db)
    for report in db.scalars(select(Analysis.dimension_report).execution_options(yield_per=100)):
        if report and any(dimension["key"] not in aliases for dimension in report.get("dimensions", [])):
            return True
    return False


def record_rank_inputs(db: Session, analysis: Analysis, inputs_fingerprint: str) -> None:
    """Persist a score-only run's captured inputs; changes made during it remain stale."""
    if analysis.opening_id is None:
        raise ValueError("A current analysis must belong to an opening.")
    analysis.rank_inputs_fingerprint = inputs_fingerprint
    db.add(analysis)
    db.commit()



def current_dimension_kinds(db: Session, opening_id: int) -> set[str]:
    """The cache ``kind`` of every dimension in the current analysis (empty if none). The
    per-(applicant, dimension) scoring cache keys on these, so both the coverage count and the
    per-candidate scoring trace resolve which cached rows belong to the live set. Reads the
    shared dimension set only — no per-member view needed."""
    from app.ai.dimension_scoring import kind_for_dimension

    analysis = get_current_analysis(db, opening_id)
    report = current_dimension_report(analysis) if analysis is not None else None
    if report is None:
        return set()
    return {kind_for_dimension(d.key) for d in report.dimensions}



def committee_kept_keys(
    db: Session, opening_id: int, report: PoolDimensionReport | None
) -> set[str]:
    """Return every dimension kept by at least one member.

    The decomposition must preserve this union so one member's re-rank cannot drop an axis
    another member relies on.

    Each member's kept set is their MOST-RECENT working-tier placement across all their
    rankings (via ``tier_history``), not just their view of the immediately-prior analysis — so
    a member who skipped the last run still protects the axes they tiered. Ignore maps to a
    non-working id, so an Ignored key is correctly excluded. Restricted to keys still present in
    ``report`` (the prior analysis's dimensions — the only axes a re-rank could carry), so a
    stale placement naming a dropped dimension can't resurrect it. Empty on a first run.
    """
    if report is None:
        return set()
    valid = {d.key for d in report.dimensions}
    kept: set[str] = set()
    for user in db.scalars(select(User).where(User.is_active.is_(True))):
        _, most_recent_tier_by_key = tier_history(db, user, opening_id, target_report=report)
        kept.update(
            key
            for key, tier_id in most_recent_tier_by_key.items()
            if tier_id != IGNORE_TIER_ID and key in valid
        )
    return kept


def committee_proposed_dimensions(db: Session, analysis: Analysis | None) -> list[str]:
    """Return the committee's pending free-text proposals for the next Rank.

    Every member's proposal steers shared discovery regardless of who triggers the run.

    Deduped case-insensitively, first-seen wording kept, stable order (members oldest-first,
    then each member's own order) so the discovery prompt reads deterministically. Proposals are
    per-analysis, so a new analysis consumes everyone's (each member's fresh ranking starts
    empty) — no clearing needed here. Empty on a first run (no prior analysis)."""
    if analysis is None:
        return []
    seen: set[str] = set()
    union: list[str] = []
    rankings = db.scalars(
        select(MemberRanking)
        .join(User)
        .where(MemberRanking.analysis_id == analysis.id, User.is_active.is_(True))
        .order_by(MemberRanking.user_id)
    ).all()
    for ranking in rankings:
        for text in proposed_dimensions(ranking):
            fold = text.strip().casefold()
            if fold and fold not in seen:
                seen.add(fold)
                union.append(text)
    return union
