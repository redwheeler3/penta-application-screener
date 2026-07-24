"""The deterministic ranked shortlist and the per-member controls that reshape it —
importance tiers and next-run discovery seeds.

The shortlist is pure math over cached dimension scores (no model call): load each candidate's
scores for the current analysis, weight by the member's tier placement, hand flat values to
``rank_candidates``. Tiers and seeds are pure per-member persistence — a tier edit returns the
re-sorted list in the same round-trip; seeds take effect on the next ``/ranking/run``.

Every endpoint here resolves the current shared ``Analysis`` plus the signed-in member's view
of it (``get_or_create_member_ranking``), so a member sees and edits their own tiering over the
shared dimensions. Tier/seed saves carry the viewed ``analysisId`` and are rejected with
``409 stale_analysis`` if it isn't current (another member re-ranked since) — inert at one
member, but keeps the contract honest for real concurrency (SPEC M15 1b).
"""

from dataclasses import asdict

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import require_current_user
from app.api.problems import Problem
from app.db.models import MemberRanking, User
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
from app.services.analysis import (
    current_dimension_report,
    dimension_weights,
    display_tiers,
    get_current_analysis,
    get_or_create_member_ranking,
    kept_keys,
    proposed_dimensions,
    requested_flag_keys,
    revived_flag_keys,
    set_proposals,
    set_tiers,
)
from app.services.eligibility import eligible_application_ids_for
from app.services.ranking_view import candidate_scores
from app.services.stars import starred_ids

router = APIRouter(prefix="/ranking")


def _current_member_view(db: Session, user: User, action: str) -> MemberRanking:
    """The signed-in member's view of the current analysis, or a 409 if none exists yet.
    ``action`` fills the "Discover patterns before {action}" message."""
    analysis = get_current_analysis(db)
    if analysis is None or current_dimension_report(analysis) is None:
        raise Problem("run_required", detail=f"Discover patterns before {action}.")
    return get_or_create_member_ranking(db, analysis, user)


def _require_viewed_analysis(db: Session, analysis_id: int, user: User) -> MemberRanking:
    """The member's view of the analysis they're editing, but only if it's still current.
    Rejects a save against a superseded analysis (another member re-ranked) with 409
    stale_analysis, rather than applying the edit to the wrong board."""
    current = get_current_analysis(db)
    if current is None or current_dimension_report(current) is None:
        raise Problem("run_required", detail="Discover patterns before tiering.")
    if current.id != analysis_id:
        raise Problem(
            "stale_analysis",
            detail="This ranking was refreshed by another member. Reload to see the new criteria.",
        )
    return get_or_create_member_ranking(db, current, user)


def _ranking_payload(db: Session, member_ranking: MemberRanking, user: User) -> RankingResponse:
    """The ranked-shortlist response for a member's view of an analysis. Shared by
    ``/ranking`` and the tier-edit endpoint, so a tier change returns the re-sorted list in one
    round-trip. Ranking weights + tiers are this member's; the dimension scores and star state
    are shared, resolved off the analysis / this user.
    """
    weights = dimension_weights(member_ranking)
    # The scored pool is the shared UNION (every applicant eligible for at least one member),
    # so restrict this member's shortlist to the applicants eligible in THEIR own view —
    # another member's eligible-only applicant is scored but must not appear on this board.
    # Pool means/impact still come from the full scored set (shared math), so a candidate's
    # numbers don't shift with who is filtering; we only drop rows the member excluded.
    eligible_ids = eligible_application_ids_for(db, user.id)
    ranked = [
        c
        for c in rank_candidates(candidate_scores(db, member_ranking.analysis), weights)
        if c.application_id in eligible_ids
    ]
    starred = starred_ids(db, user.id, [c.application_id for c in ranked])
    return RankingResponse(
        analysis_id=member_ranking.analysis_id,
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
                starred_by_me=c.application_id in starred,
            )
            for c in ranked
        ],
        # Recomputed each save so the tier-list refreshes badges in the same
        # round-trip (moving or acknowledging a flagged dimension clears it).
        new_dimension_keys=(member_ranking.run_state or {}).get("new_dimension_keys", []),
        revived_dimension_keys=revived_flag_keys(db, member_ranking),
        requested_dimension_keys=requested_flag_keys(member_ranking),
        # Kept axes (derived from tiers) + pending proposals, so the tier list and
        # composer stay in sync after a tier/seed save.
        kept_keys=kept_keys(member_ranking),
        proposed_dimensions=proposed_dimensions(member_ranking),
    )


@router.get("", response_model=RankingResponse)
def ranking(
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> RankingResponse:
    """The deterministic ranked shortlist for the signed-in member's view of the current
    analysis.

    Ranks every scored eligible candidate by the weight-normalized average of its
    dimension scores, labeled by relative pool position (no fixed cut line). Pure
    math over cached scores.
    """
    return _ranking_payload(db, _current_member_view(db, user, "ranking"), user)


# --- Tier-list weighting -----------------------------------------------------
#
# The member drags dimensions into importance tiers; weights derive from the
# layout (see ``weights_from_tiers``) and the ranking re-sorts. Pure persistence.


@router.get("/tiers", response_model=TiersResponse)
def get_tiers(
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> TiersResponse:
    """The signed-in member's tier layout for the current analysis (or the default layout if
    they have not tiered yet). 409 before an analysis exists.
    """
    member_ranking = _current_member_view(db, user, "tiering")
    return TiersResponse(tiers=[TierOut(**t) for t in display_tiers(member_ranking)])


@router.put("/tiers", response_model=RankingResponse)
def update_tiers(
    body: TierLayoutUpdate,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> RankingResponse:
    """Persist the member's new tier layout, derive weights from it, and return the freshly
    re-sorted ranking. Unknown dimension keys are rejected (422); a save against a superseded
    analysis is rejected (409 stale_analysis).
    """
    member_ranking = _require_viewed_analysis(db, body.analysis_id, user)
    layout = [t.model_dump() for t in body.tiers]
    try:
        set_tiers(
            db, member_ranking, layout,
            acknowledged_keys=body.acknowledged_keys,
            acknowledged_requested_keys=body.acknowledged_requested_keys,
        )
    except ValueError as exc:
        raise Problem("unknown_dimension_key", detail=str(exc)) from exc
    return _ranking_payload(db, member_ranking, user)


# --- Discovery seeds ---------------------------------------------------------
#
# Between runs, a member can propose free-text axes that steer the NEXT Rank's
# discovery; a proposal is consumed once a run realizes it into a real dimension.
# (An existing axis is kept across re-runs by placing it in a working tier; see kept_keys.)
# No model call here — just persistence; the proposals take effect on the next /ranking/run.


@router.put("/seeds", response_model=SeedsResponse)
def update_seeds(
    body: SeedsUpdate,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> SeedsResponse:
    """Persist the member's pending free-text proposals for the current analysis. Returns the
    current seed state. 409 before an analysis exists (nowhere to store yet) or if the viewed
    analysis was superseded (stale_analysis).
    """
    member_ranking = _require_viewed_analysis(db, body.analysis_id, user)
    set_proposals(db, member_ranking, proposed_dimensions=body.proposed_dimensions)
    return SeedsResponse(proposed_dimensions=proposed_dimensions(member_ranking))
