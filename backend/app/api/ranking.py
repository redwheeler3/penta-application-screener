"""Ranking API: the Rank chain and the deterministic ranked shortlist.

Flow the UI drives:
  1. GET  /ranking/estimate — combined cost projection for the chain.
  2. POST /ranking/run — summarize essays → find criteria → score every eligible
     applicant, streaming phase/progress/summary as NDJSON. The cap is enforced
     once over the COMBINED cost before any model call.
  3. GET  /ranking/current — the current run's criteria + summary.
  4. GET  /ranking — the ranked shortlist (math over cached scores).
  5. GET/PUT /ranking/tiers — the committee's importance-tier weighting.
  6. PUT  /ranking/seeds — discovery seeds (favourites + proposals) for next run.

The committee never runs the three sub-passes individually, so they're exposed as
one Rank step; the passes stay separate underneath (distinct schemas, cache kinds,
status behavior).
"""

import queue
import threading
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.ai.analysis import (
    PassResult,
    SpendingCapExceeded,
    enforce_cap,
    exception_type_name,
    log,
)
from app.ai.dimension_matching import estimate_match, match_dimensions
from app.ai.dimension_scoring import (
    applications_to_score,
    estimate_dimension_scoring,
    score_dimensions,
)
from app.ai.essay_analysis import (
    applications_to_analyze,
    estimate_essay_analysis,
    screen_essays,
)
from app.ai.pattern_discovery import (
    DiscoverySeeds,
    discover_patterns,
    eligible_applications,
    estimate_discovery,
)
from app.ai.provider import AIProvider
from app.api.dependencies import get_ai_provider, require_current_user
from app.api.problems import Problem
from app.db.models import User
from app.db.session import get_db
from app.domain.ranking import rank_candidates
from app.schemas.applications import DimensionContributionOut
from app.schemas.events import (
    NoticeEvent,
    PhaseEvent,
    ProgressEvent,
    RankSummary,
    ThinkingEvent,
    emit,
)
from app.schemas.events import ErrorEvent as StreamErrorEvent
from app.schemas.ranking import (
    CurrentRunResponse,
    MatchAuditResponse,
    PoolDimensionOut,
    RankedCandidateOut,
    RankEstimateBreakdown,
    RankEstimateResponse,
    RankingResponse,
    SeedsResponse,
    SeedsUpdate,
    TierLayoutUpdate,
    TierOut,
    TiersResponse,
)
from app.schemas.insights import CostReport, LastRunsReport
from app.schemas.settings import AppSettings
from app.services.cost_report import (
    cost_report,
    last_runs_report,
    ledger_pass,
    record_run_cost,
)
from app.services.ranking_view import candidate_scores
from app.services.ranking_run import (
    adopt_matched_keys,
    all_known_dimensions,
    carry_forward_layout,
    create_run,
    current_dimension_report,
    dimension_weights,
    display_tiers,
    favourited_keys,
    get_current_run,
    match_audit_view,
    proposed_dimensions,
    ranking_is_current,
    set_seeds,
    set_tiers,
    tier_history,
)
from app.services.settings import get_app_settings

router = APIRouter(prefix="/ranking", tags=["ranking"])

# Phase names for the rank stream (every event carries one, so the client's
# stream switch is uniform across this job and the screening job).
ESSAYS, CRITERIA, SCORES = "essays", "criteria", "scores"


@dataclass
class RunTally:
    """Running totals for a scoring run, emitted as the final summary line."""

    analyzed: int = 0
    cached: int = 0
    failed: int = 0
    cost_usd: float = 0.0
    # Sum of reused results' ORIGINAL cost — an estimate of what caching saved this run.
    cached_saved_usd: float = 0.0

    def add(self, result: PassResult) -> None:
        if result.failed:
            self.failed += 1
            return
        if result.fresh_units is not None or result.cached_units is not None:
            self.analyzed += result.fresh_units or 0
            self.cached += result.cached_units or 0
            self.cached_saved_usd += result.cached_saved_usd or 0.0
            self.cost_usd += result.outcome.cost_usd
            return
        if result.outcome.cached:
            # A cache hit made no model call, so it spent nothing on THIS run; its
            # stored cost is the original first-run cost, so summing it estimates what
            # regenerating would have cost (what caching saved).
            self.cached += 1
            self.cached_saved_usd += result.outcome.cost_usd
            return
        self.analyzed += 1
        self.cost_usd += result.outcome.cost_usd


def _run_payload(db: Session) -> CurrentRunResponse | None:
    """The current run's discovered pattern report, shaped for the UI."""
    run = get_current_run(db)
    if run is None:
        return None
    report = current_dimension_report(run)
    if report is None:
        return None
    return CurrentRunResponse(
        run_id=run.id,
        name=run.name,
        status=run.status,
        summary=report.summary,
        dimensions=[
            PoolDimensionOut(
                key=d.key,
                name=d.name,
                definition=d.definition,
                why_it_differentiates=d.why_it_differentiates,
                from_committee_request=d.from_committee_request,
            )
            for d in report.dimensions
        ],
        discovery_narrative=(run.criteria or {}).get("discovery_narrative"),
        # New dimensions with no confident match to a prior one — parked in Ignore,
        # flagged "new" in the UI. Empty on a first run.
        new_dimension_keys=(run.criteria or {}).get("new_dimension_keys", []),
        # Committee discovery seeds: favourited dimension keys (kept across re-runs)
        # and pending free-text proposals (fed to the next Rank, then consumed).
        favourited_keys=favourited_keys(run),
        proposed_dimensions=proposed_dimensions(run),
    )


@router.get("/current", response_model=CurrentRunResponse | None)
def current(
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> CurrentRunResponse | None:
    """The current ranking run's dimensions, or null if none discovered yet."""
    return _run_payload(db)


@router.get("/current/match-audit", response_model=MatchAuditResponse | None)
def current_match_audit(
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> MatchAuditResponse | None:
    """The current run's carry-forward audit — what discovery emitted, how the match
    pass mapped it onto prior dimensions, and the derived carry-forward rate (M13
    per-run AI legibility). Null when no run exists or the run predates the capture.
    """
    run = get_current_run(db)
    if run is None:
        return None
    view = match_audit_view(run)
    if view is None:
        return None
    return MatchAuditResponse(run_id=run.id, **view)


@router.get("/insights/cost", response_model=CostReport)
def insights_cost(
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> CostReport:
    """Cumulative AI spend for the Insights tab, grouped by run (M13 Pillar 1)."""
    return cost_report(db)


@router.get("/insights/last-runs", response_model=LastRunsReport)
def insights_last_runs(
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> LastRunsReport:
    """The most recent Screen and Rank runs, each with fresh spend + cache savings."""
    return last_runs_report(db)


# --- Rank: the combined essays → criteria → scores chain --------------------


def _rank_estimate(db: Session, settings: AppSettings) -> dict[str, Any]:
    """Combined projected cost of the Rank passes (essays → discovery → match →
    scoring).

    Essays are netted against their cache; discovery always re-runs (uncached);
    the match pass adds one small call, only when a prior run exists. Scoring is
    priced as a whole-pool ceiling (every candidate × every dimension) because the
    estimate runs before discovery, so it can't yet know how many dimensions carry
    forward. Per-dimension reuse makes the actual run come in under this ceiling,
    so the total is an upper bound (the confirmation labels it approximate).
    """
    essays = estimate_essay_analysis(db, settings)
    pool = eligible_applications(db)
    discovery_usd = estimate_discovery(pool, settings)
    # A match pass runs only when there is a prior run to match against.
    match_usd = estimate_match(settings) if get_current_run(db) is not None else 0.0
    scoring = estimate_dimension_scoring(db, settings)
    scoring_usd = float(scoring["estimated_usd"])
    total = round(
        float(essays["estimated_usd"]) + discovery_usd + match_usd + scoring_usd, 4
    )
    return {
        "eligible": len(pool),
        "breakdown": {
            "essays_usd": round(float(essays["estimated_usd"]), 4),
            "criteria_usd": round(discovery_usd, 4),
            "match_usd": round(match_usd, 4),
            "scoring_usd": round(scoring_usd, 4),
        },
        "essays_cached": essays["cached"],
        "estimated_usd": total,
        "approximate": True,  # scoring is a ceiling; carry-forward reuse lowers the real cost
    }


@router.get("/estimate", response_model=RankEstimateResponse)
def rank_estimate(
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> RankEstimateResponse:
    settings: AppSettings = get_app_settings(db)
    if not eligible_applications(db):
        raise Problem("no_eligible_applications", detail="No eligible applications to rank.")
    result = _rank_estimate(db, settings)
    cap = settings.ai.spending_cap_usd
    breakdown = result["breakdown"]
    return RankEstimateResponse(
        eligible=result["eligible"],
        breakdown=RankEstimateBreakdown(
            essays_usd=breakdown["essays_usd"],
            criteria_usd=breakdown["criteria_usd"],
            match_usd=breakdown["match_usd"],
            scoring_usd=breakdown["scoring_usd"],
        ),
        essays_cached=result["essays_cached"],
        estimated_usd=result["estimated_usd"],
        approximate=result["approximate"],
        cap_usd=cap,
        within_cap=result["estimated_usd"] <= cap,
        # When the pool is unchanged, the ranking is already current; the UI uses
        # this to say "up to date" instead of offering to spend.
        ranking_current=ranking_is_current(db, get_current_run(db), settings),
    )


@router.post("/run")
def rank_run(
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
    provider: AIProvider = Depends(get_ai_provider),
) -> StreamingResponse:
    """Run the full ranking chain — summarize essays → find criteria → score —
    streaming NDJSON. The combined cost is checked against the cap once before any
    model call, so an over-cap run fails fast with a 402 and spends nothing.

    Stream shape: a ``phase`` line per pass, ``progress`` lines for the
    per-candidate passes, then a final ``summary`` with the combined cost.
    Discovery is one call, so it emits a phase line and its result, no progress.
    """
    settings: AppSettings = get_app_settings(db)
    if not eligible_applications(db):
        raise Problem("no_eligible_applications", detail="No eligible applications to rank.")

    # An unchanged pool needs no re-rank, but we no longer block one: discovery is
    # nondeterministic, so re-running deliberately gives the committee a fresh set of
    # criteria. The confirmation card is the gate (it flags that nothing requires a
    # re-run); a member who confirms here has opted in on purpose.
    estimate = _rank_estimate(db, settings)
    try:
        enforce_cap(estimate, settings.ai.spending_cap_usd)
    except SpendingCapExceeded as exc:
        raise Problem(
            "cap_exceeded",
            detail=str(exc),
            cap_usd=settings.ai.spending_cap_usd,
            estimated_usd=float(estimate["estimated_usd"]),
        ) from exc

    def stream() -> Iterator[str]:
        total_cost = 0.0

        # Phase 1: summarize essays (informational; never touches status).
        essays = applications_to_analyze(db)
        yield emit(PhaseEvent(phase=ESSAYS, total=len(essays)))
        essay_tally = RunTally()
        for processed, result in enumerate(
            screen_essays(
                db, provider, applications=essays, settings=settings,
                max_workers=settings.ai.max_workers,
            ),
            start=1,
        ):
            essay_tally.add(result)
            yield emit(ProgressEvent(phase=ESSAYS, processed=processed, total=len(essays)))
        total_cost += essay_tally.cost_usd

        # Phase 2: find criteria (one synthesis call; starts a fresh run).
        # Capture prior state before discovery. Matching and tier carry-forward both
        # look across ALL prior runs, not just the last: a concept that fell out and
        # re-surfaces should re-adopt its existing key (reusing its cached scores) and
        # restore the committee's last tier placement for it. See SPEC "Matching scope".
        prior_run = get_current_run(db)
        prior_report = current_dimension_report(prior_run) if prior_run else None
        match_history = all_known_dimensions(db)  # every dimension ever, one per key
        scaffold_tiers, tier_by_key, known_keys = tier_history(db)
        # Committee discovery seeds: favourited dimensions (resolved to name +
        # definition from the prior report) plus pending free-text proposals. These
        # steer discovery toward axes the committee asked for; an empty seed set
        # leaves discovery fully blind (the default first-run behaviour).
        prior_favourites = favourited_keys(prior_run) if prior_run else []
        seeds = DiscoverySeeds(
            favourited=[
                {"name": d.name, "definition": d.definition}
                for d in (prior_report.dimensions if prior_report else [])
                if d.key in set(prior_favourites)
            ],
            proposed=proposed_dimensions(prior_run) if prior_run else [],
        )

        yield emit(PhaseEvent(phase=CRITERIA))
        pool = eligible_applications(db)
        # Discovery and match are single multi-minute model calls with no per-item
        # progress, so we STREAM their reasoning text as live "thinking". The
        # provider invokes on_delta from inside the call; a generator can't yield
        # from a callback, so the work runs on a worker thread that pushes deltas
        # onto a queue, and this generator drains the queue into NDJSON lines.
        # A None sentinel marks the work done; the worker stashes its outcome/error.
        delta_queue: "queue.Queue[str | None]" = queue.Queue()
        criteria_outcome: dict[str, Any] = {}

        def on_delta(text: str) -> None:
            delta_queue.put(text)

        def do_criteria() -> None:
            try:
                # Pass 1: re-discovery, blind except for the committee's seeds. With
                # no seeds this is fully blind, as before.
                report, narrative, discovery_cost = discover_patterns(
                    db, provider, applications=pool, settings=settings, seeds=seeds,
                    on_delta=on_delta,
                )
                # Pass 2: identity-match new dimensions onto ALL prior dimensions (not
                # just the last run) so a re-surfaced concept re-adopts its key rather
                # than minting a new one — keeping the key count converging and reusing
                # cached scores. Skipped on the very first run (no history).
                new_to_old: dict[str, str] = {}
                match_narrative: str | None = None
                match_cost = 0.0
                if match_history is not None:
                    new_to_old, match_narrative, match_cost = match_dimensions(
                        provider, old=match_history, new=report, settings=settings,
                        on_delta=on_delta,
                    )
                criteria_outcome["ok"] = (
                    report, narrative, discovery_cost, new_to_old, match_narrative, match_cost
                )
            except Exception as exc:  # noqa: BLE001 — surfaced to the client below
                criteria_outcome["error"] = exc
            finally:
                delta_queue.put(None)  # signal completion

        worker = threading.Thread(target=do_criteria, daemon=True)
        worker.start()
        while True:
            text = delta_queue.get()
            if text is None:
                break
            yield emit(ThinkingEvent(phase=CRITERIA, text=text))
        worker.join()

        if "error" in criteria_outcome:
            exc = criteria_outcome["error"]
            log.warning(
                "Rank criteria phase failed: %s",
                exception_type_name(exc), exc_info=exc,
            )
            yield emit(
                StreamErrorEvent(
                    phase=CRITERIA,
                    message=f"Finding criteria failed: {type(exc).__name__}: {exc}",
                )
            )
            return
        report, narrative, discovery_cost, new_to_old, match_narrative, match_cost = (
            criteria_outcome["ok"]
        )
        # Audit trail for the carry-forward: what discovery ACTUALLY emitted (its own
        # keys, before adopt_matched_keys rewrites matched ones to prior keys) and how
        # the match pass mapped it. Without this the stored report only shows the
        # rewritten result, so we can't tell genuine re-discovery from match over-
        # matching. (Exposed in the admin debug view.)
        match_audit = {
            "raw_discovery_dimensions": [
                {"key": d.key, "name": d.name, "from_committee_request": d.from_committee_request}
                for d in report.dimensions
            ],
            "new_to_old": new_to_old,
            "match_narrative": match_narrative,
            # How many prior dimensions the match pass matched against — now the full
            # cross-run history (all known keys), not just the last run. 0 on the very
            # first run (no history), so the audit viewer can tell a first run — where
            # carry-forward is N/A — from a genuine zero-match re-run.
            "prior_dimension_count": len(match_history.dimensions) if match_history else 0,
            # Prior-key → prior-name (from history), so the audit viewer can show a
            # matched dimension's user-facing prior title next to its key.
            "prior_dimension_names": (
                {d.key: d.name for d in match_history.dimensions} if match_history else {}
            ),
        }
        # Adopt the prior key for every matched dimension (keeping new descriptions)
        # so its tier placement and cached score carry forward by key alone.
        report = adopt_matched_keys(report, new_to_old)
        # Carry committee intent forward across ALL runs: restore each key's most-recent
        # tier placement; only keys never seen in any run are flagged "new".
        layout, new_dimension_keys = carry_forward_layout(
            new_report=report,
            scaffold_tiers=scaffold_tiers,
            most_recent_tier_by_key=tier_by_key,
            known_keys=known_keys,
        )
        create_run(
            db, report=report, settings=settings, model_id=settings.ai.synthesis_model,
            narrative=narrative, discovery_cost_usd=discovery_cost, match_cost_usd=match_cost,
            tier_layout=layout, new_dimension_keys=new_dimension_keys,
            # Carry prior favourites forward (by key, post-match); create_run unions
            # in any dimension the model flagged from_committee_request and clears
            # the consumed proposals.
            prior_favourited_keys=prior_favourites,
            match_audit=match_audit,
        )
        total_cost += discovery_cost + match_cost
        yield emit(
            NoticeEvent(
                phase=CRITERIA,
                dimensions=len(report.dimensions),
                carried_forward=len(new_to_old),
                new_dimensions=len(new_dimension_keys),
            )
        )

        # Phase 3: score every eligible candidate against the new dimensions.
        to_score = applications_to_score(db)
        yield emit(PhaseEvent(phase=SCORES, total=len(to_score)))
        score_tally = RunTally()
        for processed, result in enumerate(
            score_dimensions(
                db, provider, applications=to_score, report=report,
                settings=settings, max_workers=settings.ai.max_workers,
            ),
            start=1,
        ):
            score_tally.add(result)
            yield emit(ProgressEvent(phase=SCORES, processed=processed, total=len(to_score)))
        total_cost += score_tally.cost_usd

        # Persist this run's cost + cache breakdown (the only point the fresh/cached
        # split is known). Discovery and matching are always fresh calls when a Rank
        # runs — no caching — so their entries carry no cached counts.
        record_run_cost(
            db,
            kind="rank",
            passes=[
                ledger_pass(
                    "Essay analysis",
                    fresh_usd=essay_tally.cost_usd,
                    fresh_calls=essay_tally.analyzed,
                    cached_count=essay_tally.cached,
                    cached_saved_usd=essay_tally.cached_saved_usd,
                ),
                ledger_pass(
                    "Pattern discovery",
                    fresh_usd=discovery_cost, fresh_calls=1,
                    cached_count=0, cached_saved_usd=0.0,
                ),
                ledger_pass(
                    "Dimension matching",
                    fresh_usd=match_cost, fresh_calls=1 if match_cost else 0,
                    cached_count=0, cached_saved_usd=0.0,
                ),
                ledger_pass(
                    "Dimension scoring",
                    fresh_usd=score_tally.cost_usd,
                    fresh_calls=score_tally.analyzed,
                    cached_count=score_tally.cached,
                    cached_saved_usd=score_tally.cached_saved_usd,
                ),
            ],
        )

        yield emit(
            RankSummary(
                dimensions=len(report.dimensions),
                scored=score_tally.analyzed + score_tally.cached,
                failed=essay_tally.failed + score_tally.failed,
                total_cost_usd=round(total_cost, 4),
            )
        )

    return StreamingResponse(stream(), media_type="application/x-ndjson")


# --- Ranking ----------------------------------------------------------------
#
# The ranked shortlist is deterministic math over cached dimension scores — no
# model call. Loads each candidate's scores for the current run, joins dimension
# labels, and hands flat values to the pure ``rank_candidates`` domain function.


def _ranking_payload(db: Session, run) -> RankingResponse:
    """The ranked-shortlist response for a run. Shared by ``/ranking`` and the
    tier-edit endpoint, so a tier change returns the re-sorted list in one
    round-trip.
    """
    weights = dimension_weights(run)
    ranked = rank_candidates(candidate_scores(db, run), weights)
    return RankingResponse(
        run_id=run.id,
        weights=weights,
        scored_count=len(ranked),
        candidates=[
            RankedCandidateOut(
                application_id=c.application_id,
                name=c.name,
                rank=c.rank,
                fit=c.fit,
                band=c.band,
                contributions=[
                    DimensionContributionOut(**asdict(contribution))
                    for contribution in c.contributions
                ],
            )
            for c in ranked
        ],
        # Recomputed each save so the tier-list refreshes "New" badges in the same
        # round-trip (placing or acknowledging a dimension clears it).
        new_dimension_keys=(run.criteria or {}).get("new_dimension_keys", []),
        # Discovery seeds, so the criteria composer stays in sync after a tier/seed save.
        favourited_keys=favourited_keys(run),
        proposed_dimensions=proposed_dimensions(run),
    )


@router.get("", response_model=RankingResponse)
def ranking(
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> RankingResponse:
    """The deterministic ranked shortlist for the current run.

    Ranks every scored eligible candidate by the weight-normalized average of its
    dimension scores, labeled by relative pool position (no fixed cut line). Pure
    math over cached scores.
    """
    run = get_current_run(db)
    report = current_dimension_report(run) if run is not None else None
    if report is None:
        raise Problem("run_required", detail="Discover patterns before ranking.")
    return _ranking_payload(db, run)


# --- Tier-list weighting -----------------------------------------------------
#
# The committee drags dimensions into importance tiers; weights derive from the
# layout (see ``weights_from_tiers``) and the ranking re-sorts. Pure persistence.


@router.get("/tiers", response_model=TiersResponse)
def get_tiers(
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> TiersResponse:
    """The current run's tier layout (or the default single-tier layout if the
    committee has not tiered yet). 409 before a run exists.
    """
    run = get_current_run(db)
    if run is None or current_dimension_report(run) is None:
        raise Problem("run_required", detail="Discover patterns before tiering.")
    return TiersResponse(tiers=[TierOut(**t) for t in display_tiers(run)])


@router.put("/tiers", response_model=RankingResponse)
def update_tiers(
    body: TierLayoutUpdate,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> RankingResponse:
    """Persist a new tier layout, derive weights from it, and return the freshly
    re-sorted ranking. Unknown dimension keys are rejected (422).
    """
    run = get_current_run(db)
    if run is None or current_dimension_report(run) is None:
        raise Problem("run_required", detail="Discover patterns before tiering.")
    layout = [t.model_dump() for t in body.tiers]
    try:
        set_tiers(db, run, layout, acknowledged_keys=body.acknowledged_keys)
    except ValueError as exc:
        raise Problem("unknown_dimension_key", detail=str(exc)) from exc
    return _ranking_payload(db, run)


# --- Discovery seeds ---------------------------------------------------------
#
# Between runs, the committee can favourite existing dimensions (keep them across
# re-runs) and propose free-text axes. Both steer the NEXT Rank's discovery, then:
# favourites persist; proposals are consumed when a run realizes them. No model
# call here — just persistence; the seeds take effect on the next /ranking/run.


@router.put("/seeds", response_model=SeedsResponse)
def update_seeds(
    body: SeedsUpdate,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> SeedsResponse:
    """Persist the committee's discovery seeds for the current run (favourited
    dimension keys + pending proposals). Returns the current seed state. 409 before
    a run exists — there are no dimensions to favourite and nowhere to store yet.
    """
    run = get_current_run(db)
    if run is None or current_dimension_report(run) is None:
        raise Problem("run_required", detail="Discover patterns before adding seeds.")
    set_seeds(
        db, run,
        favourited_keys=body.favourited_keys,
        proposed_dimensions=body.proposed_dimensions,
    )
    return SeedsResponse(
        favourited_keys=favourited_keys(run),
        proposed_dimensions=proposed_dimensions(run),
    )
