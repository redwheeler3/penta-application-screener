"""Screening API: the Rank chain and the deterministic ranked shortlist.

Flow the UI drives:
  1. GET  /screening/rank/estimate — combined cost projection for the chain.
  2. POST /screening/rank/run — summarize essays → find criteria → score every
     eligible applicant, streaming phase/progress/summary as NDJSON. The cap is
     enforced once over the COMBINED cost before any model call.
  3. GET  /screening/current — the current run's criteria + summary.
  4. GET  /screening/ranking — the ranked shortlist (math over cached scores).
  5. GET/PUT /screening/tiers — the committee's importance-tier weighting.

The committee never runs the three sub-passes individually, so they're exposed as
one Rank step; the passes stay separate underneath (distinct schemas, cache kinds,
status behavior).
"""

import json
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.ai.analysis import ScreeningResult, SpendingCapExceeded, enforce_cap
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
from app.db.models import User
from app.db.session import get_db
from app.domain.ranking import rank_candidates
from app.services.ranking_view import candidate_scores
from app.schemas.settings import AppSettings
from app.services.screening_run import (
    adopt_matched_keys,
    carry_forward_layout,
    create_run,
    current_pattern_report,
    dimension_weights,
    display_tiers,
    favourited_keys,
    get_current_run,
    proposed_dimensions,
    ranking_is_current,
    set_seeds,
    set_tiers,
    stored_tiers,
)
from app.services.settings import get_app_settings

router = APIRouter(prefix="/screening", tags=["screening"])


@dataclass
class RunTally:
    """Running totals for a scoring run, emitted as the final summary line."""

    analyzed: int = 0
    cached: int = 0
    failed: int = 0
    cost_usd: float = 0.0

    def add(self, result: ScreeningResult) -> None:
        if result.failed:
            self.failed += 1
            return
        if result.outcome.cached:
            # A cache hit made no model call, so it spent nothing on THIS run.
            # (Its stored cost is the original first-run cost, for auditing only.)
            self.cached += 1
            return
        self.analyzed += 1
        self.cost_usd += result.outcome.cost_usd


def _run_payload(db: Session) -> dict[str, Any] | None:
    """The current run's discovered pattern report, shaped for the UI."""
    run = get_current_run(db)
    if run is None:
        return None
    report = current_pattern_report(run)
    if report is None:
        return None
    return {
        "runId": run.id,
        "name": run.name,
        "status": run.status,
        "summary": report.summary,
        "dimensions": report.model_dump(mode="json")["dimensions"],
        # New dimensions with no confident match to a prior one — parked in Ignore,
        # flagged "new" in the UI. Empty on a first run.
        "newDimensionKeys": (run.criteria or {}).get("new_dimension_keys", []),
        # Committee discovery seeds: favourited dimension keys (kept across re-runs)
        # and pending free-text proposals (fed to the next Rank, then consumed).
        "favouritedKeys": favourited_keys(run),
        "proposedDimensions": proposed_dimensions(run),
    }


@router.get("/current")
def current(
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any] | None:
    """The current screening run's dimensions, or null if none discovered yet."""
    return _run_payload(db)


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


@router.get("/rank/estimate")
def rank_estimate(
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    settings: AppSettings = get_app_settings(db)
    if not eligible_applications(db):
        raise HTTPException(status_code=409, detail="No eligible applications to rank.")
    result = _rank_estimate(db, settings)
    result["cap_usd"] = settings.ai.spending_cap_usd
    result["within_cap"] = result["estimated_usd"] <= settings.ai.spending_cap_usd
    # When the pool is unchanged, the ranking is already current; the UI uses this
    # to say "up to date" instead of offering to spend.
    result["ranking_current"] = ranking_is_current(db, get_current_run(db))
    return result


@router.post("/rank/run")
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
        raise HTTPException(status_code=409, detail="No eligible applications to rank.")

    # An unchanged pool needs no re-rank, but we no longer block one: discovery is
    # nondeterministic, so re-running deliberately gives the committee a fresh set of
    # criteria. The confirmation card is the gate (it flags that nothing requires a
    # re-run); a member who confirms here has opted in on purpose.
    estimate = _rank_estimate(db, settings)
    try:
        enforce_cap(estimate, settings.ai.spending_cap_usd)
    except SpendingCapExceeded as exc:
        raise HTTPException(status_code=402, detail=str(exc)) from exc

    def stream() -> Iterator[str]:
        total_cost = 0.0

        # Phase 1: summarize essays (informational; never touches status).
        essays = applications_to_analyze(db)
        yield json.dumps({"type": "phase", "phase": "essays", "total": len(essays)}) + "\n"
        essay_tally = RunTally()
        for processed, result in enumerate(
            screen_essays(
                db, provider, applications=essays, settings=settings,
                max_workers=settings.ai.max_workers,
            ),
            start=1,
        ):
            essay_tally.add(result)
            yield json.dumps(
                {"type": "progress", "phase": "essays", "processed": processed, "total": len(essays)}
            ) + "\n"
        total_cost += essay_tally.cost_usd

        # Phase 2: find criteria (one synthesis call; starts a fresh run).
        # Capture the prior run + tiers before discovery, to carry the committee's
        # placements forward onto the new dimensions.
        prior_run = get_current_run(db)
        prior_report = current_pattern_report(prior_run) if prior_run else None
        prior_tiers = stored_tiers(prior_run) if prior_run else []
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

        yield json.dumps({"type": "phase", "phase": "criteria"}) + "\n"
        pool = eligible_applications(db)
        try:
            # Pass 1: re-discovery, blind except for the committee's seeds (favourited
            # + proposed axes). With no seeds this is fully blind, as before.
            report, narrative, discovery_cost = discover_patterns(
                db, provider, applications=pool, settings=settings, seeds=seeds
            )
            # Pass 2: identity-match the new dimensions onto the prior ones (high
            # bar, one-to-one) so tiers + scores carry forward. Skipped on a first
            # run (no prior report) — match_dimensions returns an empty map.
            new_to_old: dict[str, str] = {}
            match_narrative: str | None = None
            match_cost = 0.0
            if prior_report is not None:
                new_to_old, match_narrative, match_cost = match_dimensions(
                    provider, old=prior_report, new=report, settings=settings
                )
        except Exception as exc:  # noqa: BLE001 — surface provider failure to the client
            yield json.dumps(
                {"type": "error", "phase": "criteria",
                 "message": f"Finding criteria failed: {type(exc).__name__}: {exc}"}
            ) + "\n"
            return
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
        }
        # Adopt the prior key for every matched dimension (keeping new descriptions)
        # so its tier placement and cached score carry forward by key alone.
        report = adopt_matched_keys(report, new_to_old)
        # Carry prior placements forward; unmatched new dimensions land in Ignore,
        # flagged "new". A first run opens with the default all-Ignore layout.
        prior_keys = {d.key for d in prior_report.dimensions} if prior_report else set()
        layout, new_dimension_keys = carry_forward_layout(
            new_report=report, old_tiers=prior_tiers, prior_keys=prior_keys
        )
        create_run(
            db, report=report, model_id=settings.ai.synthesis_model,
            narrative=narrative, cost_usd=discovery_cost + match_cost,
            tier_layout=layout, new_dimension_keys=new_dimension_keys,
            # Carry prior favourites forward (by key, post-match); create_run unions
            # in any dimension the model flagged from_committee_request and clears
            # the consumed proposals.
            prior_favourited_keys=prior_favourites,
            match_audit=match_audit,
        )
        total_cost += discovery_cost + match_cost
        yield json.dumps(
            {
                "type": "criteria_done",
                "dimensions": len(report.dimensions),
                "carriedForward": len(new_to_old),
                "newDimensions": len(new_dimension_keys),
            }
        ) + "\n"

        # Phase 3: score every eligible candidate against the new dimensions.
        to_score = applications_to_score(db)
        yield json.dumps({"type": "phase", "phase": "scores", "total": len(to_score)}) + "\n"
        score_tally = RunTally()
        for processed, result in enumerate(
            score_dimensions(
                db, provider, applications=to_score, report=report,
                settings=settings, max_workers=settings.ai.max_workers,
            ),
            start=1,
        ):
            score_tally.add(result)
            yield json.dumps(
                {"type": "progress", "phase": "scores", "processed": processed, "total": len(to_score)}
            ) + "\n"
        total_cost += score_tally.cost_usd

        yield json.dumps(
            {
                "type": "summary",
                "dimensions": len(report.dimensions),
                "scored": score_tally.analyzed + score_tally.cached,
                "failed": essay_tally.failed + score_tally.failed,
                "totalCostUsd": round(total_cost, 4),
            }
        ) + "\n"

    return StreamingResponse(stream(), media_type="application/x-ndjson")


# --- Ranking ----------------------------------------------------------------
#
# The ranked shortlist is deterministic math over cached dimension scores — no
# model call. Loads each candidate's scores for the current run, joins dimension
# labels, and hands flat values to the pure ``rank_candidates`` domain function.


def _ranking_payload(db: Session, run) -> dict[str, Any]:
    """The ranked-shortlist response for a run. Shared by ``/ranking`` and the
    tier-edit endpoint, so a tier change returns the re-sorted list in one
    round-trip.
    """
    weights = dimension_weights(run)
    ranked = rank_candidates(candidate_scores(db, run), weights)
    return {
        "runId": run.id,
        "weights": weights,
        "scoredCount": len(ranked),
        "candidates": [asdict(c) for c in ranked],
        # Recomputed each save so the tier-list refreshes "New" badges in the same
        # round-trip (placing or acknowledging a dimension clears it).
        "newDimensionKeys": (run.criteria or {}).get("new_dimension_keys", []),
        # Discovery seeds, so the criteria composer stays in sync after a tier/seed save.
        "favouritedKeys": favourited_keys(run),
        "proposedDimensions": proposed_dimensions(run),
    }


@router.get("/ranking")
def ranking(
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """The deterministic ranked shortlist for the current run.

    Ranks every scored eligible candidate by the weight-normalized average of its
    dimension scores, labeled by relative pool position (no fixed cut line). Pure
    math over cached scores.
    """
    run = get_current_run(db)
    report = current_pattern_report(run) if run is not None else None
    if report is None:
        raise HTTPException(status_code=409, detail="Discover patterns before ranking.")
    return _ranking_payload(db, run)


# --- Tier-list weighting -----------------------------------------------------
#
# The committee drags dimensions into importance tiers; weights derive from the
# layout (see ``weights_from_tiers``) and the ranking re-sorts. Pure persistence.


class TierModel(BaseModel):
    id: str
    label: str
    dimension_keys: list[str] = Field(default_factory=list)
    ignore: bool = False


class TierLayoutUpdate(BaseModel):
    tiers: list[TierModel]
    # Keys the committee acknowledged as "reviewed" this save (badge ✕ / "mark all
    # reviewed") — they drop out of new_dimension_keys even if left in Ignore.
    acknowledged_keys: list[str] = Field(default_factory=list)


@router.get("/tiers")
def get_tiers(
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """The current run's tier layout (or the default single-tier layout if the
    committee has not tiered yet). 409 before a run exists.
    """
    run = get_current_run(db)
    if run is None or current_pattern_report(run) is None:
        raise HTTPException(status_code=409, detail="Discover patterns before tiering.")
    return {"tiers": display_tiers(run)}


@router.put("/tiers")
def update_tiers(
    body: TierLayoutUpdate,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Persist a new tier layout, derive weights from it, and return the freshly
    re-sorted ranking. Unknown dimension keys are rejected (400).
    """
    run = get_current_run(db)
    if run is None or current_pattern_report(run) is None:
        raise HTTPException(status_code=409, detail="Discover patterns before tiering.")
    layout = [t.model_dump() for t in body.tiers]
    try:
        set_tiers(db, run, layout, acknowledged_keys=body.acknowledged_keys)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _ranking_payload(db, run)


# --- Discovery seeds ---------------------------------------------------------
#
# Between runs, the committee can favourite existing dimensions (keep them across
# re-runs) and propose free-text axes. Both steer the NEXT Rank's discovery, then:
# favourites persist; proposals are consumed when a run realizes them. No model
# call here — just persistence; the seeds take effect on the next /rank/run.


class SeedsUpdate(BaseModel):
    # Both optional so the UI can update one without clobbering the other.
    favourited_keys: list[str] | None = None
    proposed_dimensions: list[str] | None = None


@router.put("/seeds")
def update_seeds(
    body: SeedsUpdate,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Persist the committee's discovery seeds for the current run (favourited
    dimension keys + pending proposals). Returns the current seed state. 409 before
    a run exists — there are no dimensions to favourite and nowhere to store yet.
    """
    run = get_current_run(db)
    if run is None or current_pattern_report(run) is None:
        raise HTTPException(status_code=409, detail="Discover patterns before adding seeds.")
    set_seeds(
        db, run,
        favourited_keys=body.favourited_keys,
        proposed_dimensions=body.proposed_dimensions,
    )
    return {
        "favouritedKeys": favourited_keys(run),
        "proposedDimensions": proposed_dimensions(run),
    }
