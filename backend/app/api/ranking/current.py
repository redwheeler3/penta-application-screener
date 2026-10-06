"""Current criteria metadata and admin traces pinned to a viewed analysis."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import require_admin, require_current_user
from app.api.ranking.presentation import run_payload
from app.core.problems import Problem
from app.db.models import Analysis, User
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
    get_or_reconcile_member_ranking,
)

router = APIRouter()




@router.get("/current", response_model=CurrentRunResponse | None)
def current(
    opening_id: int | None = None,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> CurrentRunResponse | None:
    """The viewed analysis's dimensions + this member's view, or null if none discovered yet."""
    analysis = get_current_analysis(db, resolve_visible_opening_id(db, opening_id))
    if analysis is None or current_dimension_report(analysis) is None:
        return None
    return run_payload(get_or_reconcile_member_ranking(db, analysis, user))


def _viewed_analysis(db: Session, analysis_id: int, opening_id: int | None) -> Analysis:
    opening = resolve_visible_opening_id(db, opening_id)
    analysis = db.get(Analysis, analysis_id)
    if analysis is None or analysis.opening_id != opening:
        raise Problem("not_found", detail="Analysis not found for this opening.")
    return analysis


@router.get("/analyses/{analysis_id}/match-audit", response_model=MatchAuditResponse | None)
def read_match_audit(
    analysis_id: int,
    opening_id: int | None = None,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> MatchAuditResponse | None:
    """The viewed analysis's carry-forward audit — what discovery emitted, how the match
    pass mapped it onto prior dimensions, and the derived carry-forward rate. Null when
    no analysis or audit exists.
    """
    analysis = _viewed_analysis(db, analysis_id, opening_id)
    view = match_audit_view(analysis)
    if view is None:
        return None
    return MatchAuditResponse(analysis_id=analysis.id, **view)


@router.get("/analyses/{analysis_id}/decompose-audit", response_model=DecomposeAuditResponse | None)
def read_decompose_audit(
    analysis_id: int,
    opening_id: int | None = None,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> DecomposeAuditResponse | None:
    """The viewed analysis's decomposition audit — how the K fan-out discovery reports were
    settled into one non-overlapping set: each settled axis's source keys + merge/keep
    reasoning, settle-down counts, and folded committee requests. Null when no audit exists.
    """
    analysis = _viewed_analysis(db, analysis_id, opening_id)
    view = decompose_audit_view(analysis)
    if view is None:
        return None
    return DecomposeAuditResponse(analysis_id=analysis.id, **view)


@router.get("/analyses/{analysis_id}/consolidate-audit", response_model=ConsolidateAuditResponse | None)
def read_consolidate_audit(
    analysis_id: int,
    opening_id: int | None = None,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> ConsolidateAuditResponse | None:
    """The viewed analysis's consolidation audit — the post-score duplicate-merge pass:
    which correlated pairs were nominated and, per pair, whether the confirm call merged
    them (with its reasoning). Null when no audit exists.
    """
    analysis = _viewed_analysis(db, analysis_id, opening_id)
    view = consolidate_audit_view(db, analysis)
    if view is None:
        return None
    return ConsolidateAuditResponse(analysis_id=analysis.id, **view)


@router.get("/analyses/{analysis_id}/fan-out-audit", response_model=FanOutAuditResponse | None)
def read_fan_out_audit(
    analysis_id: int,
    opening_id: int | None = None,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> FanOutAuditResponse | None:
    """The viewed analysis's fan-out audit — each of the K parallel discoverers' dimensions
    + reasoning, so the discovery panel can show every discoverer, not just the one that
    streamed live. Null when no audit exists.
    """
    analysis = _viewed_analysis(db, analysis_id, opening_id)
    view = fan_out_audit_view(analysis)
    narrative = analysis.audit.discovery_narrative if analysis.audit else None
    if view is None and narrative is None:
        return None
    return FanOutAuditResponse(analysis_id=analysis.id, narrative=narrative, **(view or {"k": 0, "passes": []}))
