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
from app.db.models import User
from app.db.session import get_db
from app.schemas.ranking import (
    ConsolidateAuditResponse,
    CurrentRunResponse,
    DecomposeAuditResponse,
    FanOutAuditResponse,
    MatchAuditResponse,
    PoolDimensionOut,
)
from app.services.analysis import (
    consolidate_audit_view,
    current_dimension_report,
    decompose_audit_view,
    fan_out_audit_view,
    get_current_analysis,
    get_or_create_member_ranking,
    kept_keys,
    match_audit_view,
    proposed_dimensions,
    requested_flag_keys,
    revived_flag_keys,
)

router = APIRouter(prefix="/ranking")


def _run_payload(db: Session, user: User) -> CurrentRunResponse | None:
    """The current analysis's discovered pattern report + the signed-in member's view of it,
    shaped for the UI. The dimensions/narrative are shared; the badges, kept axes, and
    proposals are read off this member's ranking."""
    analysis = get_current_analysis(db)
    if analysis is None:
        return None
    report = current_dimension_report(analysis)
    if report is None:
        return None
    member_ranking = get_or_create_member_ranking(db, analysis, user)
    return CurrentRunResponse(
        analysis_id=analysis.id,
        dimensions=[
            PoolDimensionOut(
                key=d.key,
                name=d.name,
                definition=d.definition,
                high_end=d.high_end,
                low_end=d.low_end,
                why_it_differentiates=d.why_it_differentiates,
                from_committee_request=d.from_committee_request,
            )
            for d in report.dimensions
        ],
        discovery_narrative=analysis.audit.discovery_narrative if analysis.audit else None,
        # Dimensions absent from the immediately-prior analysis in this member's view —
        # parked/placed but flagged for triage. Empty on a first run.
        new_dimension_keys=(member_ranking.run_state or {}).get("new_dimension_keys", []),
        # Of those flagged keys, the ones seen in an EARLIER analysis (revived), derived
        # from history — the frontend colours these blue vs. amber for genuinely-new.
        revived_dimension_keys=revived_flag_keys(db, member_ranking),
        # Keys a member proposed for this analysis, not yet dismissed by them — "Requested" pill.
        requested_dimension_keys=requested_flag_keys(member_ranking),
        # Kept axes: every dimension in a working (non-Ignore) tier of this member's ranking —
        # guaranteed to survive the next Rank. Derived from tier placement (see kept_keys). Plus
        # any pending free-text proposals (fed to the next Rank, then consumed).
        kept_keys=kept_keys(member_ranking),
        proposed_dimensions=proposed_dimensions(member_ranking),
    )


@router.get("/current", response_model=CurrentRunResponse | None)
def current(
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> CurrentRunResponse | None:
    """The current analysis's dimensions + this member's view, or null if none discovered yet."""
    return _run_payload(db, user)


@router.get("/current/match-audit", response_model=MatchAuditResponse | None)
def current_match_audit(
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> MatchAuditResponse | None:
    """The current analysis's carry-forward audit — what discovery emitted, how the match
    pass mapped it onto prior dimensions, and the derived carry-forward rate (M13
    per-run AI legibility). Null when no analysis exists or it predates the capture.
    """
    analysis = get_current_analysis(db)
    if analysis is None:
        return None
    view = match_audit_view(analysis)
    if view is None:
        return None
    return MatchAuditResponse(analysis_id=analysis.id, **view)


@router.get("/current/decompose-audit", response_model=DecomposeAuditResponse | None)
def current_decompose_audit(
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> DecomposeAuditResponse | None:
    """The current analysis's decomposition audit — how the K fan-out discovery reports were
    settled into one non-overlapping set: each settled axis's source keys + merge/keep
    reasoning, the settle-down counts, and the D9 folded-committee-request trail. Null on
    analyses that predate the fan-out redesign (single-discovery runs).
    """
    analysis = get_current_analysis(db)
    if analysis is None:
        return None
    view = decompose_audit_view(analysis)
    if view is None:
        return None
    return DecomposeAuditResponse(analysis_id=analysis.id, **view)


@router.get("/current/consolidate-audit", response_model=ConsolidateAuditResponse | None)
def current_consolidate_audit(
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> ConsolidateAuditResponse | None:
    """The current analysis's consolidation audit — the post-score duplicate-merge pass:
    which correlated pairs were nominated and, per pair, whether the confirm call merged
    them (with its reasoning). Null on analyses that predate the pass.
    """
    analysis = get_current_analysis(db)
    if analysis is None:
        return None
    view = consolidate_audit_view(db, analysis)
    if view is None:
        return None
    return ConsolidateAuditResponse(analysis_id=analysis.id, **view)


@router.get("/current/fan-out-audit", response_model=FanOutAuditResponse | None)
def current_fan_out_audit(
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> FanOutAuditResponse | None:
    """The current analysis's fan-out audit — each of the K parallel discoverers' dimensions
    + reasoning, so the discovery panel can show every discoverer, not just the one that
    streamed live. Null on analyses that predate the fan-out redesign.
    """
    analysis = get_current_analysis(db)
    if analysis is None:
        return None
    view = fan_out_audit_view(analysis)
    if view is None:
        return None
    return FanOutAuditResponse(analysis_id=analysis.id, **view)
