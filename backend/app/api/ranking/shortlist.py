"""The deterministic ranked shortlist and the committee controls that reshape it —
importance tiers and next-run discovery seeds.

The shortlist is pure math over cached dimension scores (no model call): load each candidate's
scores for the current run, weight by tier placement, hand flat values to ``rank_candidates``.
Tiers and seeds are pure persistence — a tier edit returns the re-sorted list in the same
round-trip; seeds take effect on the next ``/ranking/run``.
"""

from dataclasses import asdict

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import require_current_user
from app.api.problems import Problem
from app.db.models import User
from app.db.session import get_db
from app.domain.ranking import rank_candidates
from app.schemas.applications import DimensionContributionOut
from app.schemas.ranking import (
    RankedCandidateOut,
    RankingResponse,
    SeedsResponse,
    SeedsUpdate,
    TierLayoutUpdate,
    TierOut,
    TiersResponse,
)
from app.services.ranking_run import (
    current_dimension_report,
    dimension_weights,
    display_tiers,
    get_current_run,
    kept_keys,
    proposed_dimensions,
    revived_flag_keys,
    set_proposals,
    set_tiers,
)
from app.services.ranking_view import candidate_scores

router = APIRouter(prefix="/ranking")


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
        # Recomputed each save so the tier-list refreshes badges in the same
        # round-trip (moving or acknowledging a flagged dimension clears it).
        new_dimension_keys=(run.criteria or {}).get("new_dimension_keys", []),
        revived_dimension_keys=revived_flag_keys(db, run),
        # Kept axes (derived from tiers) + pending proposals, so the tier list and
        # composer stay in sync after a tier/seed save.
        kept_keys=kept_keys(run),
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
# Between runs, the committee can propose free-text axes that steer the NEXT Rank's
# discovery; a proposal is consumed once a run realizes it into a real dimension.
# (An existing axis is kept across re-runs by placing it in a working tier; see kept_keys.)
# No model call here — just persistence; the proposals take effect on the next /ranking/run.


@router.put("/seeds", response_model=SeedsResponse)
def update_seeds(
    body: SeedsUpdate,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> SeedsResponse:
    """Persist the committee's pending free-text proposals for the current run.
    Returns the current seed state. 409 before a run exists — there is nowhere to
    store yet.
    """
    run = get_current_run(db)
    if run is None or current_dimension_report(run) is None:
        raise Problem("run_required", detail="Discover patterns before adding seeds.")
    set_proposals(db, run, proposed_dimensions=body.proposed_dimensions)
    return SeedsResponse(proposed_dimensions=proposed_dimensions(run))
