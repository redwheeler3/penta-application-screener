"""The current analysis's criteria + its AI-legibility audits.

``/current`` returns the analysis's discovered dimensions (what the member ranks against) plus
the signed-in member's view of them (tier badges, kept axes, proposals); the four
``/current/*-audit`` endpoints expose how those dimensions were produced — the fan-out
discoverers, the decomposition that settled them, the match pass's carry-forward, and the
post-score consolidation. Dimensions and audits are shared; the badges/kept/proposals are
per-member. Each audit is null on analyses that predate its capture. No model calls — pure
reads over the persisted analysis + member ranking.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import require_current_user
from app.api.ranking.presentation import run_payload
from app.db.models import User
from app.db.session import get_db
from app.schemas.ranking import (
    ConsolidateAuditResponse,
    CurrentRunResponse,
    DecomposeAuditResponse,
    FanOutAuditResponse,
    MatchAuditResponse,
)
from app.services.applications.scope import resolve_visible_opening_id
from app.services.ranking.analysis import get_current_analysis
from app.services.ranking.audit import (
    consolidate_audit_view,
    decompose_audit_view,
    fan_out_audit_view,
    match_audit_view,
)
from app.services.ranking.dimensions import current_dimension_report
from app.services.ranking.member_state import (
    get_or_create_member_ranking,
)

router = APIRouter()




@router.get("/current", response_model=CurrentRunResponse | None)
def current(
    opening_id: int | None = None,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> CurrentRunResponse | None:
    """The current analysis's dimensions + this member's view, or null if none discovered yet."""
    analysis = get_current_analysis(db, resolve_visible_opening_id(db, opening_id))
    if analysis is None or current_dimension_report(analysis) is None:
        return None
    return run_payload(db, get_or_create_member_ranking(db, analysis, user))


@router.get("/current/match-audit", response_model=MatchAuditResponse | None)
def current_match_audit(
    opening_id: int | None = None,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> MatchAuditResponse | None:
    """The current analysis's carry-forward audit — what discovery emitted, how the match
    pass mapped it onto prior dimensions, and the derived carry-forward rate. Null when
    no analysis or audit exists.
    """
    analysis = get_current_analysis(db, resolve_visible_opening_id(db, opening_id))
    if analysis is None:
        return None
    view = match_audit_view(analysis)
    if view is None:
        return None
    return MatchAuditResponse(analysis_id=analysis.id, **view)


@router.get("/current/decompose-audit", response_model=DecomposeAuditResponse | None)
def current_decompose_audit(
    opening_id: int | None = None,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> DecomposeAuditResponse | None:
    """The current analysis's decomposition audit — how the K fan-out discovery reports were
    settled into one non-overlapping set: each settled axis's source keys + merge/keep
    reasoning, settle-down counts, and folded committee requests. Null when no audit exists.
    """
    analysis = get_current_analysis(db, resolve_visible_opening_id(db, opening_id))
    if analysis is None:
        return None
    view = decompose_audit_view(analysis)
    if view is None:
        return None
    return DecomposeAuditResponse(analysis_id=analysis.id, **view)


@router.get("/current/consolidate-audit", response_model=ConsolidateAuditResponse | None)
def current_consolidate_audit(
    opening_id: int | None = None,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> ConsolidateAuditResponse | None:
    """The current analysis's consolidation audit — the post-score duplicate-merge pass:
    which correlated pairs were nominated and, per pair, whether the confirm call merged
    them (with its reasoning). Null when no audit exists.
    """
    analysis = get_current_analysis(db, resolve_visible_opening_id(db, opening_id))
    if analysis is None:
        return None
    view = consolidate_audit_view(db, analysis)
    if view is None:
        return None
    return ConsolidateAuditResponse(analysis_id=analysis.id, **view)


@router.get("/current/fan-out-audit", response_model=FanOutAuditResponse | None)
def current_fan_out_audit(
    opening_id: int | None = None,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> FanOutAuditResponse | None:
    """The current analysis's fan-out audit — each of the K parallel discoverers' dimensions
    + reasoning, so the discovery panel can show every discoverer, not just the one that
    streamed live. Null when no audit exists.
    """
    analysis = get_current_analysis(db, resolve_visible_opening_id(db, opening_id))
    if analysis is None:
        return None
    view = fan_out_audit_view(analysis)
    if view is None:
        return None
    return FanOutAuditResponse(analysis_id=analysis.id, **view)
