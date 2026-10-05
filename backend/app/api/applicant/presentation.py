"""HTTP response assembly for applicant access, pending copies, and openings."""

from datetime import datetime

from sqlalchemy.orm import Session

from app.core.time import as_utc
from app.db.models import ApplicantDraft, Application, MagicLinkToken, OpeningPhase
from app.schemas.applicant.contracts import (
    AccessLinkResponse,
    ApplicantOpeningOut,
    PendingCopyOut,
)
from app.services.applications.access import (
    applicant_link_state,
    draft_answers,
    link_targets_other_application,
)
from app.services.applications.answers import working_answers_for
from app.services.openings.participation import ApplicantOpeningState


def access_link_response(
    db: Session,
    link: MagicLinkToken | None,
    current: Application | None,
    *,
    now: datetime | None = None,
) -> AccessLinkResponse:
    if link is None:
        return AccessLinkResponse(state="invalid")
    state = applicant_link_state(db, link, now=now)
    return AccessLinkResponse(
        state=state,
        purpose=link.purpose,
        current_email=current.primary_email if current is not None else None,
        link_email=link.email,
        application_email=(link.application.primary_email if link.application is not None else None),
        switch_required=link_targets_other_application(link, current),
        application_id=current.id if current is not None else None,
        pending_intent=link.applicant_draft.intent if link.applicant_draft is not None else None,
    )


def pending_copy(application: Application, draft: ApplicantDraft) -> PendingCopyOut:
    saved = working_answers_for(application)
    guest = draft_answers(draft)
    if saved is None or guest is None:
        raise ValueError("pending-copy comparison requires two readable working copies")
    return PendingCopyOut(
        base_revision=application.working_revision,
        guest_saved_at=as_utc(draft.saved_at),
        saved_answers=saved,
        saved_opening_ids=list(application.working_opening_ids or []),
        guest_answers=guest,
        guest_opening_ids=list(draft.working_opening_ids or []),
    )


def applicant_openings(states: list[ApplicantOpeningState]) -> list[ApplicantOpeningOut]:
    """Offer closed openings only to applicants still participating in them."""
    return [_applicant_opening(state) for state in states
            if state.phase != OpeningPhase.CLOSED or state.participating]


def _applicant_opening(state: ApplicantOpeningState) -> ApplicantOpeningOut:
    opening = state.opening
    return ApplicantOpeningOut(
        id=opening.id,
        unit_size_bedrooms=opening.unit_size_bedrooms,
        housing_charge_cents=opening.housing_charge_cents,
        application_open_date=opening.application_open_date.isoformat(),
        application_close_date=opening.application_close_date.isoformat(),
        move_in_date=opening.move_in_date.isoformat(),
        phase=state.phase,
        selected=state.selected,
        participating=state.participating,
        has_participated=state.has_participated,
        can_select=state.can_select,
        can_withdraw=state.can_withdraw,
    )
