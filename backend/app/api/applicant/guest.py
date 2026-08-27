"""Applicant-owned pending drafts, identity links, and published applications."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.applicant.dependencies import (
    optional_current_application,
)
from app.api.applicant.support import (
    _access_target_is_editable,
    _applicant_opening,
    _new_applications_are_open,
    _require_application_editable,
    _require_current_revision,
    _require_matching_email,
    _require_new_applications_open,
)
from app.core.config import get_settings
from app.core.problems import Problem
from app.core.text import normalize_email
from app.db.models import (
    ApplicantDraft,
    ApplicantDraftIntent,
    Application,
    MagicLinkPurpose,
    PasswordlessIdentityKind,
)
from app.db.session import get_db
from app.schemas.applicant_intake import (
    AccessLinkRequest,
    ApplicantOpeningsResponse,
    GuestSubmissionCheckRequest,
    GuestSubmissionCheckResponse,
    GuestSubmitApplicationRequest,
    GuestSubmitApplicationResponse,
    PendingDraftRequest,
    PendingDraftResponse,
    RequestAccessLinkRequest,
    RequestAccessLinkResponse,
)
from app.services.applicant_drafts import (
    applicant_email_request_allowed,
    latest_pending_draft_for_email,
    pending_draft_for_token,
    revoke_other_pending_drafts,
    save_collision_copy,
    save_pending_draft,
)
from app.services.email_sender import EmailSender, get_email_sender
from app.services.intake import (
    create_application,
    publish_working_copy,
    save_working_copy,
)
from app.services.magic_link_delivery import (
    EmailSendOutcome,
    send_application_confirmation,
    send_application_unavailable,
    send_magic_link,
)
from app.services.opening_participation import (
    applicant_opening_states,
    application_is_editable,
    validate_opening_selection,
    validate_working_opening_selection,
)

router = APIRouter()


@router.get("/openings", response_model=ApplicantOpeningsResponse)
def read_applicant_openings(db: Session = Depends(get_db)) -> ApplicantOpeningsResponse:
    states = applicant_opening_states(db, None)
    return ApplicantOpeningsResponse(
        can_start_application=any(state.can_select for state in states),
        openings=[_applicant_opening(state) for state in states],
    )


@router.post("/submissions/check", response_model=GuestSubmissionCheckResponse)
def check_guest_submission(
    body: GuestSubmissionCheckRequest,
    db: Session = Depends(get_db),
    sender: EmailSender = Depends(get_email_sender),
) -> GuestSubmissionCheckResponse:
    """Stop an existing application at the pre-review boundary and email its owner."""
    now = datetime.now(UTC)
    email = normalize_email(str(body.answers.applicant.email))
    application = db.scalar(
        select(Application).where(
            Application.primary_email == email,
            Application.deleted_at.is_(None),
        )
    )
    if application is None:
        return GuestSubmissionCheckResponse(can_submit=True)
    validate_working_opening_selection(db, None, body.opening_ids, now=now)
    draft = save_collision_copy(
        db,
        application=application,
        answers=body.answers,
        opening_ids=body.opening_ids,
        now=now,
    )
    revoke_other_pending_drafts(db, draft, now=now)
    outcome = send_magic_link(
        db,
        sender,
        identity_kind=PasswordlessIdentityKind.APPLICANT,
        purpose=MagicLinkPurpose.APPLICANT_ACCESS,
        email=email,
        recipient_id=draft.id,
        applicant_draft=draft,
        now=now,
    )
    return GuestSubmissionCheckResponse(
        can_submit=False,
        email_sent=outcome.email_sent,
        email_status=outcome.value,
    )

@router.post("/drafts", response_model=PendingDraftResponse, status_code=status.HTTP_202_ACCEPTED)
def save_applicant_draft(
    body: PendingDraftRequest,
    db: Session = Depends(get_db),
    sender: EmailSender = Depends(get_email_sender),
) -> PendingDraftResponse:
    _require_new_applications_open(db)
    now = datetime.now(UTC)
    validate_working_opening_selection(db, None, body.opening_ids, now=now)
    saved = save_pending_draft(
        db,
        answers=body.answers,
        opening_ids=body.opening_ids,
        intent=body.intent,
        draft_token=body.draft_token,
        now=now,
    )
    can_send = applicant_email_request_allowed(db, saved.record.email, now=now)
    outcome = EmailSendOutcome.RECENT
    if can_send:
        outcome = send_magic_link(
            db,
            sender,
            identity_kind=PasswordlessIdentityKind.APPLICANT,
            purpose=MagicLinkPurpose.APPLICANT_ACCESS,
            email=saved.record.email,
            recipient_id=saved.record.id,
            applicant_draft=saved.record,
            now=now,
            enforce_request_limits=False,
        )
    if not can_send:
        db.commit()
    return PendingDraftResponse(
        draft_token=saved.token,
        email_sent=outcome.email_sent,
        email_status=outcome.value,
        retry_after_seconds=get_settings().magic_link_coalesce_seconds,
    )


@router.post(
    "/submissions",
    response_model=GuestSubmitApplicationResponse,
    status_code=status.HTTP_201_CREATED,
)
def submit_guest_application(
    body: GuestSubmitApplicationRequest,
    db: Session = Depends(get_db),
    sender: EmailSender = Depends(get_email_sender),
) -> GuestSubmitApplicationResponse:
    """Publish a first application without making email access a submission gate."""
    if not body.declaration_accepted:
        raise Problem("declaration_required", detail="Accept the declaration before submitting.")
    _require_new_applications_open(db)
    now = datetime.now(UTC)
    email = normalize_email(str(body.answers.applicant.email))
    existing = db.scalar(
        select(Application).where(
            Application.primary_email == email,
            Application.deleted_at.is_(None),
        )
    )
    if existing is not None:
        send_magic_link(
            db,
            sender,
            identity_kind=PasswordlessIdentityKind.APPLICANT,
            purpose=MagicLinkPurpose.APPLICANT_ACCESS,
            email=email,
            recipient_id=existing.id,
            application_id=existing.id,
            now=now,
        )
        raise Problem(
            "application_already_exists",
            detail="An application already exists for this email. Check your inbox for a link to open it.",
        )

    openings = validate_opening_selection(db, None, body.opening_ids, now=now)
    application = create_application(
        db,
        email,
        body.answers,
        saved_at=now,
        opening_ids=body.opening_ids,
    )
    publish_working_copy(db, application, body.answers, openings, submitted_at=now)
    if body.draft_token is not None:
        draft = pending_draft_for_token(db, body.draft_token)
        if draft is not None and draft.email == email:
            draft.application_id = application.id
            draft.resolved_at = now
    db.commit()
    sent = send_application_confirmation(db, sender, application, submitted=True, now=now)
    return GuestSubmitApplicationResponse(
        email_sent=sent,
        email_status="sent" if sent else "failed",
    )


@router.delete("/drafts", status_code=status.HTTP_204_NO_CONTENT)
def delete_applicant_draft(
    body: AccessLinkRequest, db: Session = Depends(get_db)
) -> Response:
    record = pending_draft_for_token(db, body.token)
    if record is not None:
        record.revoked_at = datetime.now(UTC)
        db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/access-links/request",
    response_model=RequestAccessLinkResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def request_applicant_access_link(
    body: RequestAccessLinkRequest,
    current: Application | None = Depends(optional_current_application),
    db: Session = Depends(get_db),
    sender: EmailSender = Depends(get_email_sender),
) -> RequestAccessLinkResponse:
    """Save a new or authenticated draft, or return to an existing private record.

    A signed-out request never writes its browser answers over an existing application or
    pending draft. The response shape is identical in every branch so an address cannot be
    used to enumerate applicants.
    """
    now = datetime.now(UTC)
    email = normalize_email(str(body.answers.applicant.email))

    if current is not None:
        _require_application_editable(db, current)
        _require_matching_email(current, body.answers)
        _require_current_revision(current, body.base_revision)
        validate_working_opening_selection(db, current, body.opening_ids, now=now)
        save_working_copy(
            current,
            body.answers,
            saved_at=now,
            opening_ids=body.opening_ids,
        )
        target: Application | ApplicantDraft = current
    else:
        application = db.scalar(
            select(Application).where(
                Application.primary_email == email,
                Application.deleted_at.is_(None),
            )
        )
        if application is not None and not application_is_editable(
            applicant_opening_states(db, application)
        ):
            sent = send_application_unavailable(
                db, sender, email, application=application, now=now
            )
            return RequestAccessLinkResponse(
                current_answers_saved=False,
                email_status="sent" if sent else "failed",
            )
        draft = latest_pending_draft_for_email(db, email, now=now)
        if draft is not None:
            if not _access_target_is_editable(db, draft):
                sent = send_application_unavailable(db, sender, email, now=now)
                return RequestAccessLinkResponse(
                    current_answers_saved=False,
                    email_status="sent" if sent else "failed",
                )
            target = draft
        elif application is not None:
            target = application
        else:
            if not _new_applications_are_open(db):
                sent = send_application_unavailable(db, sender, email, now=now)
                return RequestAccessLinkResponse(
                    current_answers_saved=False,
                    email_status="sent" if sent else "failed",
                )
            validate_working_opening_selection(db, None, body.opening_ids, now=now)
            open_ids = [
                state.opening.id
                for state in applicant_opening_states(db, None)
                if state.can_select
            ]
            saved = save_pending_draft(
                db,
                answers=body.answers,
                opening_ids=body.opening_ids,
                retention_opening_ids=open_ids,
                intent=ApplicantDraftIntent.SAVE,
                now=now,
            )
            target = saved.record

    can_send = applicant_email_request_allowed(db, email, now=now)
    outcome = EmailSendOutcome.RECENT
    if can_send:
        outcome = send_magic_link(
            db,
            sender,
            identity_kind=PasswordlessIdentityKind.APPLICANT,
            purpose=MagicLinkPurpose.APPLICANT_ACCESS,
            email=email,
            recipient_id=target.id,
            application_id=target.id if isinstance(target, Application) else None,
            applicant_draft=target if isinstance(target, ApplicantDraft) else None,
            now=now,
            enforce_request_limits=False,
        )
    else:
        db.commit()

    return RequestAccessLinkResponse(
        current_answers_saved=current is not None,
        email_status=outcome.value,
    )
