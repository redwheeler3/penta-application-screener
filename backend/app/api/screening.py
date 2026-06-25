"""Screening API: the Rank chain (milestones 6-8) and the deterministic ranked
shortlist (milestone 8).

Flow the UI drives:
  1. GET  /screening/rank/estimate — combined cost projection for the chain.
  2. POST /screening/rank/run — summarize essays → find criteria → score every
     eligible applicant, streaming phase/progress/summary as NDJSON. The cap is
     enforced once over the COMBINED cost before any model call.
  3. GET  /screening/current — the current run's criteria + summary.
  4. GET  /screening/ranking — the ranked shortlist (math over cached scores).
  5. GET/PUT /screening/tiers — the committee's importance-tier weighting (M9).

The committee never runs the three sub-passes individually, so they are exposed
as the single Rank step; the passes stay separate underneath (distinct schemas,
cache kinds, and status behavior).
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
from app.ai.dimension_matching import match_dimensions
from app.ai.dimension_scoring import (
    applications_to_score,
    estimate_scoring_without_dimensions,
    screen_dimension_scores,
)
from app.ai.essay_analysis import (
    applications_to_analyze,
    estimate_essay_analysis,
    screen_essays,
)
from app.ai.pattern_discovery import (
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
    carry_forward_layout,
    create_run,
    current_pattern_report,
    dimension_weights,
    display_tiers,
    get_current_run,
    ranking_is_current,
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
            # (A cached outcome carries its original first-run cost for auditing;
            # that is not money spent now, so it must not count toward the total.)
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
        # Dimensions that appeared on the last re-discovery with no confident match
        # to a prior dimension — parked in Ignore for the committee to triage, and
        # flagged "new" in the tier-list UI. Empty on a first run.
        "newDimensionKeys": (run.criteria or {}).get("new_dimension_keys", []),
    }


@router.get("/current")
def current(
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any] | None:
    """The current screening run's dimensions, or null if none discovered yet."""
    return _run_payload(db)


# --- Rank: the combined essays → criteria → scores chain --------------------
#
# The committee never runs the three sub-passes individually, so the UI exposes
# them as one "Rank" button. The passes stay separate underneath (distinct
# schemas, cache kinds, and status behavior — essay summary and scoring never
# touch status, discovery starts a fresh run); this layer just orchestrates them
# back-to-back. The spending cap is enforced once, over the COMBINED projected
# cost, before any model call — so the single button keeps the same hard cost
# gate as the individual passes had.


def _rank_estimate(db: Session, settings: AppSettings) -> dict[str, Any]:
    """Combined projected cost of the three Rank passes.

    Essay summary is netted against its cache (re-running is cheap if essays were
    already summarized). Discovery always re-runs (uncached) and scoring is
    priced for the whole eligible pool, because Rank discovers a fresh dimension
    set every time — so no prior scores are cache hits under it. The total is
    therefore an upper-ish bound; the confirmation labels it approximate.
    """
    essays = estimate_essay_analysis(db, settings)
    pool = eligible_applications(db)
    discovery_usd = estimate_discovery(pool, settings)
    scoring = estimate_scoring_without_dimensions(db, settings)
    scoring_usd = float(scoring["estimated_usd"])
    total = round(float(essays["estimated_usd"]) + discovery_usd + scoring_usd, 4)
    return {
        "eligible": len(pool),
        "breakdown": {
            "essays_usd": round(float(essays["estimated_usd"]), 4),
            "criteria_usd": round(discovery_usd, 4),
            "scoring_usd": round(scoring_usd, 4),
        },
        "essays_cached": essays["cached"],
        "estimated_usd": total,
        "approximate": True,  # criteria/scoring scale with essay output not yet produced
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
    # When the pool hasn't changed since the last run, the ranking is already
    # current — re-running would only re-pay for an identical result. The UI uses
    # this to say "ranking is up to date" instead of offering to spend.
    result["ranking_current"] = ranking_is_current(db, get_current_run(db))
    return result


@router.post("/rank/run")
def rank_run(
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
    provider: AIProvider = Depends(get_ai_provider),
) -> StreamingResponse:
    """Run the full ranking chain — summarize essays → find criteria → score —
    streaming NDJSON. The combined cost is checked against the cap once, before
    any model call, so an over-cap run fails fast with a 402 and spends nothing.

    Stream shape: a ``phase`` line announces each pass (essays / criteria /
    scores), then ``progress`` lines for the per-candidate passes, then a final
    ``summary`` with the combined cost. Discovery is one call, so it emits a
    phase line and its standalone result, no progress fraction.
    """
    settings: AppSettings = get_app_settings(db)
    if not eligible_applications(db):
        raise HTTPException(status_code=409, detail="No eligible applications to rank.")

    # Block a no-op re-run: if the eligible pool is unchanged since the current
    # run, the ranking is already current and re-running would only re-spend for
    # an identical result (discovery is nondeterministic, so it would even churn
    # the criteria and force a full re-score). The pool must change to re-rank.
    if ranking_is_current(db, get_current_run(db)):
        raise HTTPException(
            status_code=409,
            detail="Ranking is already current for this applicant pool. "
            "Sync new or changed applications before re-ranking.",
        )

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
        # Capture the PRIOR run and its tier layout before discovery, so we can
        # carry the committee's placements forward onto the new dimensions.
        prior_run = get_current_run(db)
        prior_report = current_pattern_report(prior_run) if prior_run else None
        prior_tiers = stored_tiers(prior_run) if prior_run else []

        yield json.dumps({"type": "phase", "phase": "criteria"}) + "\n"
        pool = eligible_applications(db)
        try:
            # Pass 1: blind re-discovery — never sees the prior dimensions.
            report, narrative, discovery_cost = discover_patterns(
                db, provider, applications=pool, settings=settings
            )
            # Pass 2: identity-match the new dimensions onto the prior ones (high
            # bar, one-to-one) so tiers + scores carry forward. Skipped on a first
            # run (no prior report) — match_dimensions returns an empty map.
            new_to_old: dict[str, str] = {}
            match_cost = 0.0
            if prior_report is not None:
                new_to_old, _match_narrative, match_cost = match_dimensions(
                    provider, old=prior_report, new=report, settings=settings
                )
        except Exception as exc:  # noqa: BLE001 — surface provider failure to the client
            yield json.dumps(
                {"type": "error", "phase": "criteria",
                 "message": f"Finding criteria failed: {type(exc).__name__}: {exc}"}
            ) + "\n"
            return
        # Carry the prior placements forward; unmatched new dimensions land in
        # Ignore and are flagged "new". A first run (no prior tiers) opens with the
        # default all-Ignore layout and nothing flagged.
        layout, new_dimension_keys = carry_forward_layout(
            new_report=report, old_tiers=prior_tiers, new_to_old=new_to_old
        )
        create_run(
            db, report=report, model_id=settings.ai.synthesis_model,
            narrative=narrative, cost_usd=discovery_cost + match_cost,
            tier_layout=layout, new_dimension_keys=new_dimension_keys,
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
            screen_dimension_scores(
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


# --- Ranking (milestone 8) --------------------------------------------------
#
# The ranked shortlist is deterministic math over the cached dimension scores —
# no model call. This layer loads each eligible candidate's scores for the
# current run, joins the dimension labels, and hands flat values to the pure
# ``rank_candidates`` domain function. The run's equal-weight baseline lives in
# ``criteria.weights``; M9 will mutate it, and re-ranking is just a re-fetch.


def _ranking_payload(db: Session, run) -> dict[str, Any]:
    """The ranked-shortlist response for a run. Shared by ``/ranking`` and the
    tier-edit endpoint, so a tier change returns the freshly re-sorted list in the
    same shape — the client re-sorts in one round-trip.
    """
    report = current_pattern_report(run)
    weights = dimension_weights(run)
    ranked = rank_candidates(candidate_scores(db, report), weights)
    return {
        "runId": run.id,
        "weights": weights,
        "scoredCount": len(ranked),
        "candidates": [asdict(c) for c in ranked],
        # Recomputed each save so the tier-list can refresh "New" badges in the
        # same round-trip (placing or acknowledging a dimension clears it).
        "newDimensionKeys": (run.criteria or {}).get("new_dimension_keys", []),
    }


@router.get("/ranking")
def ranking(
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """The deterministic ranked shortlist for the current run.

    Ranks every scored eligible candidate by the weight-normalized average of its
    dimension scores and labels each by relative pool position. The committee
    reads the stack-ranked list top-down — there is no fixed cut line. No model
    call — pure math over cached scores.
    """
    run = get_current_run(db)
    report = current_pattern_report(run) if run is not None else None
    if report is None:
        raise HTTPException(status_code=409, detail="Discover patterns before ranking.")
    return _ranking_payload(db, run)


# --- Tier-list weighting (milestone 9) --------------------------------------
#
# The committee drags discovered dimensions into self-defined importance tiers;
# weights derive from the layout (see ``weights_from_tiers``) and the ranking
# re-sorts. No model call — pure persistence + the existing ranking math.


class TierModel(BaseModel):
    id: str
    label: str
    dimension_keys: list[str] = Field(default_factory=list)
    ignore: bool = False


class TierLayoutUpdate(BaseModel):
    tiers: list[TierModel]
    # Dimension keys the committee explicitly acknowledged as "reviewed" this save
    # (badge ✕ / "mark all reviewed") — they drop out of new_dimension_keys even
    # if left in Ignore. Placing a dimension in a working tier clears it anyway.
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
