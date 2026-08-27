"""Member feedback: submit from any page (any member), read + resolve (admin only).

The write route is open to every member — it's their channel to flag friction. Reads
are admin-only because the free text is potentially sensitive (a member may paste
applicant specifics). Identity, app version, and time are stamped server-side, never
taken from the request body, so a feedback row is always attributable to a real member
and build.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.dependencies import require_admin, require_current_user
from app.core.problems import Problem
from app.db.models import Feedback, User
from app.db.session import get_db
from app.schemas.feedback import FeedbackCreate, FeedbackListResponse, FeedbackOut
from app.services import feedback as feedback_service
from app.version import app_version

router = APIRouter(prefix="/feedback", tags=["feedback"])


def _to_out(feedback: Feedback, applicant_names: dict[int, str]) -> FeedbackOut:
    return FeedbackOut(
        id=feedback.id,
        body=feedback.body,
        user_email=feedback.user.email,
        user_name=feedback.user.display_name,
        route=feedback.route,
        active_tab=feedback.active_tab,
        analysis_id=feedback.analysis_id,
        applicant_id=feedback.applicant_id,
        applicant_name=(
            applicant_names.get(feedback.applicant_id)
            if feedback.applicant_id is not None
            else None
        ),
        app_version=feedback.app_version,
        created_at=feedback.created_at,
        resolved_at=feedback.resolved_at,
    )


@router.post("", response_model=FeedbackOut, status_code=201)
def submit_feedback(
    body: FeedbackCreate,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> FeedbackOut:
    """Record a member's feedback. Identity + app version are stamped here (not trusted
    from the body); route/tab/analysis are the context the client reported."""
    feedback = feedback_service.create_feedback(
        db,
        user_id=user.id,
        body=body.body,
        app_version=app_version(),
        route=body.route,
        active_tab=body.active_tab,
        analysis_id=body.analysis_id,
        applicant_id=body.applicant_id,
    )
    # Eager-load isn't needed: the submitting user is already in the session identity map.
    return _to_out(feedback, feedback_service.applicant_names_for(db, [feedback]))


@router.get("", response_model=FeedbackListResponse)
def list_feedback(
    # camelCase on the wire, per the app's query/body contract.
    include_resolved: bool = Query(default=False, alias="includeResolved"),
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> FeedbackListResponse:
    """List feedback newest-first. Open items only by default; ``includeResolved=true``
    widens to the full history."""
    items = feedback_service.list_feedback(db, include_resolved=include_resolved)
    names = feedback_service.applicant_names_for(db, items)
    return FeedbackListResponse(items=[_to_out(f, names) for f in items])


@router.post("/{feedback_id}/resolve", response_model=FeedbackOut)
def resolve_feedback(
    feedback_id: int,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> FeedbackOut:
    """Mark an item handled (idempotent). It leaves the open list but is retained."""
    feedback = feedback_service.resolve_feedback(db, feedback_id)
    if feedback is None:
        raise Problem("not_found", detail="Feedback not found.")
    return _to_out(feedback, feedback_service.applicant_names_for(db, [feedback]))


@router.post("/{feedback_id}/reopen", response_model=FeedbackOut)
def reopen_feedback(
    feedback_id: int,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> FeedbackOut:
    """Move a resolved item back to the open list (idempotent)."""
    feedback = feedback_service.reopen_feedback(db, feedback_id)
    if feedback is None:
        raise Problem("not_found", detail="Feedback not found.")
    return _to_out(feedback, feedback_service.applicant_names_for(db, [feedback]))
