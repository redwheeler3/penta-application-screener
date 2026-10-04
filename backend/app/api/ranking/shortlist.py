"""The deterministic ranked shortlist and the per-member controls that reshape it —
importance tiers and next-run discovery seeds.

The shortlist is pure math over cached dimension scores (no model call): load each candidate's
scores for the current analysis, weight by the member's tier placement, hand flat values to
``rank_candidates``. Tiers and seeds are pure per-member persistence — a tier edit returns the
re-sorted list in the same round-trip; seeds take effect on the next ``/ranking/run``.

Every endpoint here resolves the current shared ``Analysis`` plus the signed-in member's view
of it (``get_or_create_member_ranking``), so a member sees and edits their own tiering over the
shared dimensions. Tier/seed saves carry the viewed ``analysisId`` and are rejected with
``409 stale_analysis`` if it isn't current, protecting concurrent members from writing to a
superseded analysis.
"""


from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import require_current_user
from app.api.ranking.presentation import ranking_payload, run_payload
from app.core.problems import Problem
from app.db.models import MemberRanking, User
from app.db.session import get_db
from app.schemas.ranking import (
    RankingBoardResponse,
    RankingResponse,
    SeedsResponse,
    SeedsUpdate,
    TierLayoutUpdate,
    TierOut,
    TiersResponse,
)
from app.services.applications.scope import resolve_visible_opening_id
from app.services.ranking.analysis import get_current_analysis
from app.services.ranking.dimensions import current_dimension_report
from app.services.ranking.member_state import (
    display_tiers,
    get_or_create_member_ranking,
    proposed_dimensions,
    set_proposals,
    set_tiers,
)
from app.services.run_lock import lock_run_state, rank_run_in_progress

router = APIRouter(prefix="/ranking")


def _current_member_view(
    db: Session, user: User, opening_id: int, action: str
) -> MemberRanking:
    """The signed-in member's view of the current analysis, or a 409 if none exists yet.
    ``action`` fills the "Discover patterns before {action}" message."""
    analysis = get_current_analysis(db, opening_id)
    if analysis is None or current_dimension_report(analysis) is None:
        raise Problem("run_required", detail=f"Discover patterns before {action}.")
    return get_or_create_member_ranking(db, analysis, user)


def _require_viewed_analysis(
    db: Session, opening_id: int, analysis_id: int, user: User
) -> MemberRanking:
    """The member's view of the analysis they're editing, but only if it's safe to save.
    Rejects a save against a superseded analysis (another member re-ranked) with 409
    stale_analysis; and rejects a save WHILE a rank run is in flight, because that run has
    already snapshotted the committee kept-list and will supersede this analysis — so a tier
    edit made now (e.g. dragging an axis out of Ignore) would neither reach the run nor survive
    it, and could vanish. Blocking the save (not just warning) is what prevents the loss: the
    member re-does the edit against the fresh board once the run lands."""
    lock_run_state(db)
    if rank_run_in_progress(db):
        raise Problem(
            "run_in_progress",
            detail="A ranking is in progress. Try again in about 10 minutes, then make your "
            "changes on the refreshed criteria.",
        )
    current = get_current_analysis(db, opening_id)
    if current is not None:
        db.refresh(current)
    if current is None or current_dimension_report(current) is None:
        raise Problem("run_required", detail="Discover patterns before tiering.")
    if current.id != analysis_id:
        raise Problem(
            "stale_analysis",
            detail="This ranking was refreshed by another member. Reload to see the new criteria.",
        )
    return get_or_create_member_ranking(db, current, user, commit=False)




@router.get("/board", response_model=RankingBoardResponse)
def ranking_board(
    opening_id: int | None = None,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> RankingBoardResponse:
    """Criteria, scores, and tiers from the same captured member view."""
    resolved = resolve_visible_opening_id(db, opening_id)
    member_ranking = _current_member_view(db, user, resolved, "ranking")
    run = run_payload(db, member_ranking)
    if run is None:
        raise Problem("run_required", detail="Discover patterns before ranking.")
    return RankingBoardResponse(
        run=run, ranking=ranking_payload(db, member_ranking, user),
        tiers=[TierOut(**tier) for tier in display_tiers(member_ranking)],
    )


@router.get("", response_model=RankingResponse)
def ranking(
    opening_id: int | None = None,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> RankingResponse:
    """The deterministic ranked shortlist for the signed-in member's view of the current
    analysis.

    Ranks every scored eligible candidate by the weight-normalized average of its
    dimension scores, labeled by relative pool position (no fixed cut line). Pure
    math over cached scores.
    """
    resolved = resolve_visible_opening_id(db, opening_id)
    return ranking_payload(db, _current_member_view(db, user, resolved, "ranking"), user)


# --- Tier-list weighting -----------------------------------------------------
#
# The member drags dimensions into importance tiers; weights derive from the
# layout (see ``weights_from_tiers``) and the ranking re-sorts. Pure persistence.


@router.get("/tiers", response_model=TiersResponse)
def get_tiers(
    opening_id: int | None = None,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> TiersResponse:
    """The signed-in member's tier layout for the current analysis (or the default layout if
    they have not tiered yet). 409 before an analysis exists.
    """
    member_ranking = _current_member_view(
        db, user, resolve_visible_opening_id(db, opening_id), "tiering"
    )
    return TiersResponse(tiers=[TierOut(**t) for t in display_tiers(member_ranking)])


@router.put("/tiers", response_model=RankingResponse)
def update_tiers(
    body: TierLayoutUpdate,
    opening_id: int | None = None,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> RankingResponse:
    """Persist the member's new tier layout, derive weights from it, and return the freshly
    re-sorted ranking. Unknown dimension keys are rejected (422); a save against a superseded
    analysis is rejected (409 stale_analysis).
    """
    member_ranking = _require_viewed_analysis(
        db, resolve_visible_opening_id(db, opening_id), body.analysis_id, user
    )
    layout = [t.model_dump() for t in body.tiers]
    try:
        set_tiers(
            db, member_ranking, layout,
            acknowledged_keys=body.acknowledged_keys,
            acknowledged_requested_keys=body.acknowledged_requested_keys,
        )
    except ValueError as exc:
        raise Problem("unknown_dimension_key", detail=str(exc)) from exc
    return ranking_payload(db, member_ranking, user)


# --- Discovery seeds ---------------------------------------------------------
#
# Between runs, a member can propose free-text axes that steer the NEXT Rank's
# discovery; a proposal is consumed once a run realizes it into a real dimension.
# (An existing axis is kept across re-runs by placing it in a working tier; see kept_keys.)
# No model call here — just persistence; the proposals take effect on the next /ranking/run.


@router.put("/seeds", response_model=SeedsResponse)
def update_seeds(
    body: SeedsUpdate,
    opening_id: int | None = None,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> SeedsResponse:
    """Persist the member's pending free-text proposals for the current analysis. Returns the
    current seed state. 409 before an analysis exists (nowhere to store yet) or if the viewed
    analysis was superseded (stale_analysis).
    """
    member_ranking = _require_viewed_analysis(
        db, resolve_visible_opening_id(db, opening_id), body.analysis_id, user
    )
    set_proposals(db, member_ranking, proposed_dimensions=body.proposed_dimensions)
    return SeedsResponse(proposed_dimensions=proposed_dimensions(member_ranking))
