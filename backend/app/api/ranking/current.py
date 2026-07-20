"""The current ranking run's criteria + its AI-legibility audits.

``/current`` returns the run's discovered dimensions (what the committee ranks against);
the four ``/current/*-audit`` endpoints expose how those dimensions were produced — the
fan-out discoverers, the decomposition that settled them, the match pass's carry-forward, and
the post-score consolidation. Each audit is null on runs that predate its capture. No model
calls — pure reads over the persisted run.
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
from app.services.ranking_run import (
    consolidate_audit_view,
    current_dimension_report,
    decompose_audit_view,
    fan_out_audit_view,
    get_current_run,
    kept_keys,
    match_audit_view,
    proposed_dimensions,
    revived_flag_keys,
)

router = APIRouter(prefix="/ranking")


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
        discovery_narrative=run.audit.discovery_narrative if run.audit else None,
        # Dimensions absent from the immediately-prior run — parked/placed but flagged
        # for triage. Empty on a first run.
        new_dimension_keys=(run.run_state or {}).get("new_dimension_keys", []),
        # Of those flagged keys, the ones seen in an EARLIER run (revived), derived
        # from history — the frontend colours these blue vs. amber for genuinely-new.
        revived_dimension_keys=revived_flag_keys(db, run),
        # Kept axes: every dimension in a working (non-Ignore) tier — guaranteed to
        # survive the next Rank. Derived from tier placement (see kept_keys). Plus any
        # pending free-text proposals (fed to the next Rank, then consumed).
        kept_keys=kept_keys(run),
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


@router.get("/current/decompose-audit", response_model=DecomposeAuditResponse | None)
def current_decompose_audit(
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> DecomposeAuditResponse | None:
    """The current run's decomposition audit — how the K fan-out discovery reports were
    settled into one non-overlapping set: each settled axis's source keys + merge/keep
    reasoning, the settle-down counts, and the D9 folded-committee-request trail. Null on
    runs that predate the fan-out redesign (single-discovery runs).
    """
    run = get_current_run(db)
    if run is None:
        return None
    view = decompose_audit_view(run)
    if view is None:
        return None
    return DecomposeAuditResponse(run_id=run.id, **view)


@router.get("/current/consolidate-audit", response_model=ConsolidateAuditResponse | None)
def current_consolidate_audit(
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> ConsolidateAuditResponse | None:
    """The current run's consolidation audit — the post-score duplicate-merge pass:
    which correlated pairs were nominated and, per pair, whether the confirm call merged
    them (with its reasoning). Null on runs that predate the pass.
    """
    run = get_current_run(db)
    if run is None:
        return None
    view = consolidate_audit_view(db, run)
    if view is None:
        return None
    return ConsolidateAuditResponse(run_id=run.id, **view)


@router.get("/current/fan-out-audit", response_model=FanOutAuditResponse | None)
def current_fan_out_audit(
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> FanOutAuditResponse | None:
    """The current run's fan-out audit — each of the K parallel discoverers' dimensions
    + reasoning, so the discovery panel can show every discoverer, not just the one that
    streamed live. Null on runs that predate the fan-out redesign.
    """
    run = get_current_run(db)
    if run is None:
        return None
    view = fan_out_audit_view(run)
    if view is None:
        return None
    return FanOutAuditResponse(run_id=run.id, **view)
