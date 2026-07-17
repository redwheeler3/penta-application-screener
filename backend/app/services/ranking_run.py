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
from app.db.models import (
    Application,
    ApplicationStatus,
    DimensionAlias,
    RankingRun,
    SyncRun,
)
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
    pass the Rank chain runs (discovery + decompose + match → scoring). So a re-rank is
    flagged current only when the pool, every rank-chain prompt, AND every rank-chain
    model are unchanged since the run was created — editing any rank-chain prompt or
    switching a model correctly shows Rank as stale, not just a pool change. (Screening
    is the separate Screen step, not part of Rank, so it's excluded.)

    Prompt versions are imported lazily: the AI passes import this module, so a
    top-level import would be circular (matches the existing local-import pattern in
    ``estimate_match``).
    """
    from app.ai.dimension_consolidate import PROMPT_VERSION as CONSOLIDATE_V
    from app.ai.dimension_decompose import PROMPT_VERSION as DECOMPOSE_V
    from app.ai.dimension_matching import PROMPT_VERSION as MATCH_V
    from app.ai.dimension_scoring import PROMPT_VERSION as SCORING_V
    from app.ai.pattern_discovery import PROMPT_VERSION as DISCOVERY_V

    parts = [
        pool_fingerprint(db),
        f"discovery:{DISCOVERY_V}",
        f"decompose:{DECOMPOSE_V}",
        f"match:{MATCH_V}",
        f"scoring:{SCORING_V}",
        f"consolidate:{CONSOLIDATE_V}",
        # The model of every rank-chain pass — a change to any of them ambers Rank.
        # Screening's model is deliberately absent: it's the separate Screen step.
        f"discovery_model:{settings.ai.discovery_model}",
        f"decompose_model:{settings.ai.decompose_model}",
        f"match_model:{settings.ai.match_model}",
        f"scoring_model:{settings.ai.dimension_scoring_model}",
        f"consolidate_model:{settings.ai.consolidate_model}",
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


def create_run(
    db: Session,
    *,
    report: PoolDimensionReport,
    settings: AppSettings,
    model_id: str,
    narrative: str | None,
    name: str = "Ranking run",
    tier_layout: list[dict] | None = None,
    new_dimension_keys: list[str] | None = None,
    prior_favourited_keys: list[str] | None = None,
    match_audit: dict | None = None,
    fan_out_audit: dict | None = None,
    decompose_audit: dict | None = None,
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
    # Link the run to the sync whose pool it ranked over — the most recent import. This
    # records the run's data provenance (which imported pool it scored), which the eval
    # synthetic-source guard reads to decide whether the pool's evidence is safe to commit.
    # None when nothing has been imported yet (shouldn't happen — ranking needs a pool).
    latest_sync_id = db.scalar(select(SyncRun.id).order_by(SyncRun.id.desc()).limit(1))
    run = RankingRun(
        name=name,
        status="patterns_discovered",
        source_sync_run_id=latest_sync_id,
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
            # Carry-forward audit: raw pre-adopt discovery dims + the match map +
            # match narrative, so a re-rank's "what changed" is inspectable (genuine
            # re-discovery vs. match over-matching). None on a first run (no match).
            "match_audit": match_audit,
            # Fan-out audit (SPEC "Fan-Out Redesign"): the K raw discovery reports this
            # run produced, before decomposition settled them into one set. None on runs
            # written before fan-out landed (single-discovery runs).
            "fan_out_audit": fan_out_audit,
            # Decompose audit (SPEC "Fan-Out Redesign", Phase 4a): per settled axis, the
            # source_keys it absorbed + the merge/keep reasoning (the Insights surface +
            # the D9 committee-request trail). None on runs written before decomposition.
            "decompose_audit": decompose_audit,
        },
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _flatten_merges(merges: dict[str, str]) -> dict[str, str]:
    """Resolve every drop→keep to its terminal survivor, collapsing in-run chains.

    ``{C: B, B: A}`` becomes ``{C: A, B: A}``. Orientation is always newer→older
    (canonical rank), so the links strictly decrease and can't cycle; the ``seen`` cap
    is defensive only.
    """
    resolved: dict[str, str] = {}
    for drop, keep in merges.items():
        seen = {drop}
        while keep in merges and keep not in seen:
            seen.add(keep)
            keep = merges[keep]
        resolved[drop] = keep
    return resolved


def apply_consolidation(
    db: Session,
    run: RankingRun,
    *,
    merges: dict[str, str],
    audit: list[dict],
    narrative: str | None,
) -> RankingRun:
    """Fold confirmed duplicate keys into their canonical key on an already-persisted
    run (the post-score consolidation pass; SPEC "Post-score consolidation").

    ``merges`` maps each dropped (newer) key → its kept (older/canonical) key. For each:
    persist a ``DimensionAlias`` row (so future matches adopt the canonical key), drop
    the loser from this run's ``dimension_report``, and remove it from every tier — the
    winner already carries its own tier placement + cached scores, so the loser's rows
    simply become orphaned cache (harmless, like any dropped dimension).

    A merge can also heal a CROSS-RUN fork, where the surviving ``keep`` is a PRIOR-run
    key that never appeared in THIS run (this run discovered only the newer ``drop``
    twin; the definition-match pass missed it, but score-vector correlation caught it).
    There the winner is *not* already in the report, so dropping the loser alone would
    delete the axis entirely. Instead we surface the canonical prior key itself — bring
    back its frozen MINT record and restore the working tier the committee last placed
    it in — rather than renaming ``drop`` (keys must never be mixed up: cache identity
    and committee tier/flag history both ride on the exact key). Weights are
    re-derived from the collapsed tiers. Always records the ``consolidate_audit``
    (even with zero merges — the pass ran), for Insights. The pass's cost lands in the
    run cost ledger, not here.
    """
    criteria = dict(run.criteria or {})

    # A single run's merges can form a chain: if C→B correlates higher than B→A, the
    # confirm loop emits {C: B, B: A}. Flatten every drop to its TERMINAL survivor
    # ({C: A, B: A}) so aliases point straight at the winner and every by-value lookup
    # below (favourite transfer especially) lands on a key that still exists, not a
    # mid-chain key that was itself dropped.
    merges = _flatten_merges(merges)

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
                db.add(DimensionAlias(alias_key=drop_key, canonical_key=keep_key, reason=reason))
            else:
                # Keep the alias pointing at the current canonical key + latest reason.
                row.canonical_key = keep_key
                row.reason = reason

        report = criteria.get("dimension_report") or {}
        report_dims = [
            d for d in report.get("dimensions", []) if d.get("key") not in merges
        ]

        # Cross-run fork heal: a surviving ``keep`` that isn't in this run's report is a
        # PRIOR-run key this run never re-discovered on its own — only the newer ``drop``
        # twin surfaced, the definition-match pass missed the fork, and score-vector
        # correlation caught it here. Dropping the loser alone would delete the axis, so
        # surface the canonical key itself: bring back its FROZEN MINT record (never the
        # drop's re-worded text — cache identity rides on the exact key), and restore the
        # working tier the committee last placed it in (same revival path a normally
        # re-surfacing key takes, via tier_history's most-recent placement).
        present = {d.get("key") for d in report_dims}
        resurfaced = [k for k in dict.fromkeys(merges.values()) if k not in present]
        if resurfaced:
            history = all_known_dimensions(db)
            mint_by_key = {d.key: d for d in history.dimensions} if history else {}
            _scaffold, most_recent_tier_by_key, _known = tier_history(db)
            # Only keys we can actually rebuild from a mint record get surfaced+placed.
            resurfaced = [k for k in resurfaced if k in mint_by_key]
            report_dims.extend(mint_by_key[k].model_dump(mode="json") for k in resurfaced)
        report["dimensions"] = report_dims
        criteria["dimension_report"] = report

        tiers = [
            {**t, "dimension_keys": [k for k in t.get("dimension_keys", []) if k not in merges]}
            for t in (criteria.get("tiers") or [])
        ]
        if resurfaced:
            tier_by_id = {t["id"]: t for t in tiers}
            placed = {k for t in tiers for k in t["dimension_keys"]}
            for keep_key in resurfaced:
                target = most_recent_tier_by_key.get(keep_key)
                # Restore its last working-tier placement; an unknown/absent tier or a
                # last-left-in-Ignore key stays unplaced (lands in the derived Ignore
                # zone) — mirrors carry_forward_layout, never forces a tier.
                if keep_key not in placed and target is not None and target in tier_by_id:
                    tier_by_id[target]["dimension_keys"].append(keep_key)
        criteria["tiers"] = tiers
        surviving = [d.get("key") for d in report["dimensions"]]
        criteria["weights"] = weights_from_tiers(surviving, tiers)
        # A dropped key can't stay flagged "new".
        criteria["new_dimension_keys"] = [
            k for k in (criteria.get("new_dimension_keys") or []) if k not in merges
        ]
        # A merged-away key can't stay favourited (it no longer exists in the run). If
        # the committee favourited the dropped key, the favourite transfers to the
        # surviving canonical key so the intent — "keep this axis" — is preserved.
        favourited = criteria.get("favourited_keys") or []
        criteria["favourited_keys"] = sorted(
            {merges.get(k, k) for k in favourited}
        )

    # Persisted for EVERY run the pass ran on, merges or not. Each pair row carries both
    # judged definitions (definition_keep/definition_drop), so this audit is the durable,
    # self-contained record of a consolidation decision — critical on a MERGE, where the
    # dropped dimension has just been removed from dimension_report above and would
    # otherwise leave no definition behind to evaluate the merge against.
    criteria["consolidate_audit"] = {
        "merges": merges,
        "pairs": audit,
        "narrative": narrative,
    }

    run.criteria = criteria  # reassign so SQLAlchemy tracks the JSON change
    db.commit()
    db.refresh(run)
    return run


def get_current_run(db: Session) -> RankingRun | None:
    """The most recent ranking run, or None if discovery has never run."""
    return db.scalar(select(RankingRun).order_by(RankingRun.id.desc()).limit(1))


def alias_map(db: Session) -> dict[str, str]:
    """Every consolidation alias, resolved to its TERMINAL canonical key.

    Follows chains (A→B, B→C ⇒ A→C, B→C) so a later merge of a canonical key forwards
    the aliases already pointing at it. The post-score consolidation pass writes these;
    the match input resolves through them so a re-minted duplicate re-adopts the
    canonical key. Cycles (shouldn't occur — merges always point newer→older) are broken
    defensively by capping the walk.
    """
    direct = {a.alias_key: a.canonical_key for a in db.scalars(select(DimensionAlias))}
    resolved: dict[str, str] = {}
    for start in direct:
        cur = direct[start]
        seen = {start}
        while cur in direct and cur not in seen:
            seen.add(cur)
            cur = direct[cur]
        resolved[start] = cur
    return resolved


def key_history(db: Session) -> tuple[dict[str, int], dict[str, str]]:
    """For consolidation: (canonical_rank, definitions) over every key ever discovered.

    ``canonical_rank[key]`` = the id of the EARLIEST run the key appeared in — so a
    lower rank means older, and consolidation keeps the older key on a merge (maximizing
    cache carry-forward). ``definitions[key]`` = the key's MINT definition (its earliest
    appearance), for the confirm prompt to judge a nominated pair. One pass, oldest first.

    Definition is the mint, not the newest, for the same key/text immutability reason as
    ``all_known_dimensions``: a key's cached scores were computed against the text it was
    minted with, so the confirm call must judge that text — not a later re-worded version
    that would divorce the definition from the scores it reasons about. Rank and
    definition therefore come from the SAME (earliest) run; they used to disagree (rank
    oldest, definition newest), which let a key's judged wording drift off its scores.
    """
    runs = db.scalars(select(RankingRun).order_by(RankingRun.id.asc())).all()
    rank: dict[str, int] = {}
    definitions: dict[str, str] = {}
    for run in runs:
        report = current_dimension_report(run)
        if report is None:
            continue
        for dim in report.dimensions:
            rank.setdefault(dim.key, run.id)  # first (oldest) run wins the rank
            definitions.setdefault(dim.key, dim.definition)  # and the mint definition
    return rank, definitions


def all_known_dimensions(db: Session) -> PoolDimensionReport | None:
    """Every distinct concept ever discovered, one entry per key, each carrying the text
    it was MINTED with — a synthetic report for the identity-match pass.

    The match pass matches a fresh discovery against this whole history, not just the
    last run — so a concept that fell out of a run and re-surfaced is recognized and
    RE-ADOPTS its existing key, instead of minting a new one. That keeps the distinct
    key count converging on the true number of concepts (~20-25) rather than growing a
    few per run, and (because the score cache is keyed by dimension key) lets those
    re-adopted keys reuse their cached scores. See SPEC "Matching scope".

    **Key/text immutability invariant.** A key's descriptive text (definition, poles,
    why-it-differentiates) is FROZEN when the key is minted and never changes, because
    the score cache is keyed by key and every cached score was computed against that
    frozen text. Different text ⇒ a different key. So this returns each key's *own mint*
    definition (its earliest appearance), and a retired alias key NEVER donates its
    wording to the canonical key it merged into: the canonical's text was frozen at its
    own mint and its scores match THAT text, so overwriting it with a duplicate's
    (differently-scoped) wording would silently divorce the definition from the scores.
    (This bug did occur: a run-6 merge aliased a broad `hands_on_trade_skills` onto the
    narrow-minted `licensed_trade_skills`; the donation made match+adopt carry the broad
    text forward onto run-1's narrow scores. Freezing to the mint prevents it and
    self-heals — the narrow mint is what the cached scores were computed against.)

    Consolidation aliases are still resolved to their canonical key, so a key a prior run
    retired as a duplicate never re-enters the match target set — but only the canonical's
    OWN entry supplies text; the alias contributes nothing. Returns None when no run has
    ever discovered dimensions.
    """
    aliases = alias_map(db)
    # Oldest run first, so the first time we see a key is its MINT — the frozen text its
    # cached scores were computed against. A later run's re-worded re-discovery of the
    # same key is ignored (the invariant: text can't drift under a key).
    runs = db.scalars(select(RankingRun).order_by(RankingRun.id.asc())).all()
    minted_by_key: dict[str, PoolDimension] = {}
    for run in runs:
        report = current_dimension_report(run)
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


def mark_ranking_current(db: Session, run: RankingRun, settings: AppSettings) -> None:
    """Record the committee's choice to keep this run's criteria for current inputs."""
    run.criteria = {
        **(run.criteria or {}),
        "rank_inputs_fingerprint": rank_inputs_fingerprint(db, settings),
    }
    db.add(run)
    db.commit()


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
    # Which discovery report(s) coined each source key, derived from the fan-out audit
    # (source key -> [report index]). A key in several reports = independent re-discovery.
    # Empty on runs whose fan-out wasn't captured; the UI then just omits the R-labels.
    key_to_reports: dict[str, list[int]] = {}
    fan_out = (run.criteria or {}).get("fan_out_audit") or {}
    for i, p in enumerate(fan_out.get("passes", [])):
        for dim in (p.get("report") or {}).get("dimensions", []):
            key_to_reports.setdefault(dim.get("key"), []).append(i)
    settled = [
        {
            **s,
            "source_report_map": {
                sk: key_to_reports[sk] for sk in s.get("source_keys", []) if sk in key_to_reports
            },
        }
        for s in audit.get("settled", [])
    ]
    return {
        "input_report_count": audit.get("input_report_count", 0),
        "input_dimension_count": audit.get("input_dimension_count", 0),
        "settled_count": audit.get("settled_count", 0),
        "merge_count": audit.get("merge_count", 0),
        "settled": settled,
        "folded_requests": audit.get("folded_requests", []),
        "narrative": audit.get("narrative"),
    }


def consolidate_audit_view(run: RankingRun) -> dict | None:
    """The run's consolidation audit — the correlation-nominated duplicate pairs and the
    confirm verdict on each — shaped for the trace viewer, or None on runs that predate
    the pass (no ``criteria.consolidate_audit``).

    ``pairs`` are every nominated pair with its correlation ``r``, whether it ``merged``,
    and the model's ``reason``. ``merges`` is the applied ``drop_key -> keep_key`` map.
    Thin pass-through with defaults, mirroring the other ``*_audit_view`` accessors.
    """
    audit = (run.criteria or {}).get("consolidate_audit")
    if not audit:
        return None
    pairs = audit.get("pairs", [])
    return {
        "merges": audit.get("merges", {}),
        "pairs": pairs,
        "nominated_count": len(pairs),
        "merged_count": sum(1 for p in pairs if p.get("merged")),
        "narrative": audit.get("narrative"),
    }


def fan_out_audit_view(run: RankingRun) -> dict | None:
    """The run's fan-out audit — each of the K parallel discoverers' report + reasoning —
    shaped for the Insights discovery panel, or None on runs that predate the fan-out
    (single-discovery runs have no ``criteria.fan_out_audit``, or an older shape).

    Returns ``{k, passes: [{dimensions: [{key,name,definition,why...}], narrative}]}``.
    Older audits stored ``reports`` without per-pass narratives; those are tolerated
    (narrative comes back null) so the panel still renders their dimensions. Any extra
    keys in a stored report are ignored — only the fields above are projected.
    """
    audit = (run.criteria or {}).get("fan_out_audit")
    if not audit:
        return None
    # Current shape: passes = [{report, narrative}]. Legacy shape: reports = [report].
    raw_passes = audit.get("passes")
    if raw_passes is None:
        raw_passes = [{"report": r, "narrative": None} for r in audit.get("reports", [])]

    passes = []
    for p in raw_passes:
        report = p.get("report") or {}
        passes.append(
            {
                "dimensions": [
                    {
                        "key": d.get("key", ""),
                        "name": d.get("name", ""),
                        "definition": d.get("definition", ""),
                        "why_it_differentiates": d.get("why_it_differentiates", ""),
                    }
                    for d in report.get("dimensions", [])
                ],
                "narrative": p.get("narrative"),
            }
        )
    return {"k": audit.get("k", len(passes)), "passes": passes}


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
