"""Authenticated applicant reads, edits, submission, email change, and withdrawal."""

from collections.abc import Callable
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.applicant.dependencies import require_current_application
from app.api.applicant.presentation import (
    applicant_openings,
    pending_copy,
)
from app.core.config import get_settings
from app.core.problems import Problem
from app.core.text import normalize_email
from app.core.time import as_utc
from app.db.models import (
    ApplicantDraft,
    Application,
    ApplicationParticipation,
    BrowserSession,
    MagicLinkPurpose,
    PasswordlessIdentityKind,
)
from app.db.session import get_db
from app.schemas.applicant.contracts import (
    ApplicantApplicationResponse,
    EmailChangeRequest,
    EmailChangeResponse,
    PendingCopyResponse,
    ReconcilePendingCopyRequest,
    SaveApplicationRequest,
    SubmitApplicationRequest,
    WithdrawApplicationResponse,
)
from app.services.applications.access import (
    draft_answers,
    draft_belongs_to_application,
    lock_application_revision,
    pending_email_change,
    require_application_editable,
    require_application_not_selected,
    require_matching_email,
)
from app.services.applications.answers import (
    working_answers_for,
)
from app.services.applications.drafts import revoke_application_drafts
from app.services.applications.intake import (
    publish_working_copy,
    save_working_copy,
)
from app.services.applications.locking import lock_application
from app.services.applications.purge import purge_never_submitted_application
from app.services.applications.retention import refresh_application_retention
from app.services.auth.passwordless import (
    revoke_identity_magic_links,
    revoke_identity_sessions,
)
from app.services.email.delivery import cancel_queued_application_emails
from app.services.email.sender import EmailSender, get_email_sender
from app.services.email.transactional import (
    queue_submission_confirmation,
    send_magic_link,
)
from app.services.maintenance import get_outbox_runner
from app.services.openings.participation import (
    applicant_opening_states,
    application_is_editable,
    validate_opening_selection,
    validate_working_opening_selection,
)

router = APIRouter()


@router.get("/application/pending-copy", response_model=PendingCopyResponse)
def get_pending_copy(
    request: Request,
    application: Application = Depends(require_current_application),
) -> PendingCopyResponse:
    session: BrowserSession = request.state.passwordless_session
    draft = session.reconciliation_draft
    if not draft_belongs_to_application(draft, application):
        return PendingCopyResponse()
    return PendingCopyResponse(pending_copy=pending_copy(application, draft))


@router.post("/application/pending-copy", status_code=status.HTTP_204_NO_CONTENT)
def reconcile_pending_copy(
    body: ReconcilePendingCopyRequest,
    request: Request,
    application: Application = Depends(require_current_application),
    db: Session = Depends(get_db),
) -> Response:
    lock_application_revision(db, application, body.base_revision)
    session: BrowserSession = request.state.passwordless_session
    draft = session.reconciliation_draft
    if draft is not None:
        draft = db.get(ApplicantDraft, draft.id, populate_existing=True)
    if not draft_belongs_to_application(draft, application):
        raise Problem("pending_copy_not_found", detail="These answers are no longer available.")
    if as_utc(draft.saved_at) != as_utc(body.guest_saved_at):
        raise Problem(
            "pending_copy_changed",
            detail="These guest answers changed while you were comparing them. Review the copies again.",
        )
    if body.choice == "guest":
        require_application_editable(db, application)
        answers = draft_answers(draft)
        if answers is None:
            raise Problem("pending_copy_invalid", detail="These answers cannot be restored.")
        validate_working_opening_selection(
            db, application, draft.working_opening_ids or [], now=datetime.now(UTC)
        )
        save_working_copy(
            application,
            answers,
            saved_at=datetime.now(UTC),
            opening_ids=draft.working_opening_ids,
        )
    draft.resolved_at = datetime.now(UTC)
    session.reconciliation_draft_id = None
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

@router.get("/application", response_model=ApplicantApplicationResponse)
def get_applicant_application(
    application: Application = Depends(require_current_application),
    db: Session = Depends(get_db),
) -> ApplicantApplicationResponse:
    opening_states = applicant_opening_states(db, application, use_working_copy=True)
    return ApplicantApplicationResponse(
        application_id=application.id,
        primary_email=application.primary_email,
        google_sign_in_linked=application.google_subject is not None,
        pending_email_change=pending_email_change(db, application.id),
        answers=working_answers_for(application),
        working_saved_at=(
            as_utc(application.working_saved_at)
            if application.working_saved_at is not None
            else None
        ),
        working_revision=application.working_revision,
        submitted=application.submitted_at is not None,
        can_edit=application_is_editable(db, application, opening_states),
        openings=applicant_openings(opening_states),
    )


@router.post(
    "/application/email-change",
    response_model=EmailChangeResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def request_applicant_email_change(
    body: EmailChangeRequest,
    request: Request,
    application: Application = Depends(require_current_application),
    db: Session = Depends(get_db),
    sender: EmailSender = Depends(get_email_sender),
) -> EmailChangeResponse:
    require_application_not_selected(db, application)
    new_email = normalize_email(str(body.new_email))
    if new_email == normalize_email(application.primary_email):
        raise Problem("email_unchanged", detail="Enter a different email address.")
    outcome = send_magic_link(
        db,
        sender,
        identity_kind=PasswordlessIdentityKind.APPLICANT,
        purpose=MagicLinkPurpose.EMAIL_CHANGE,
        email=new_email,
        recipient_id=application.id,
        application_id=application.id,
        initiating_session_id=request.state.passwordless_session.id,
    )
    pending_email = pending_email_change(db, application.id)
    return EmailChangeResponse(
        email_sent=outcome.email_sent,
        email_status=outcome.value,
        retry_after_seconds=get_settings().magic_link_coalesce_seconds,
        pending_email=pending_email,
    )


@router.delete("/application/email-change", status_code=status.HTTP_204_NO_CONTENT)
def cancel_applicant_email_change(
    application: Application = Depends(require_current_application),
    db: Session = Depends(get_db),
) -> Response:
    require_application_not_selected(db, application)
    cancel_queued_application_emails(db, application.id,
        purpose=MagicLinkPurpose.EMAIL_CHANGE, error_code="EmailChangeCancelled")
    revoke_identity_magic_links(
        db,
        identity_kind=PasswordlessIdentityKind.APPLICANT,
        application_id=application.id,
        purpose=MagicLinkPurpose.EMAIL_CHANGE,
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/application", response_model=ApplicantApplicationResponse)
def save_applicant_application(
    body: SaveApplicationRequest,
    db: Session = Depends(get_db),
    application: Application = Depends(require_current_application),
) -> ApplicantApplicationResponse:
    lock_application_revision(db, application, body.base_revision)
    require_application_editable(db, application)
    require_matching_email(application, body.answers)
    now = datetime.now(UTC)
    validate_working_opening_selection(db, application, body.opening_ids, now=now)
    save_working_copy(
        application,
        body.answers,
        saved_at=now,
        opening_ids=body.opening_ids,
    )
    db.flush()
    acknowledged = get_applicant_application(application, db)
    db.commit()
    return acknowledged


@router.post("/application/submit", response_model=ApplicantApplicationResponse)
def submit_applicant_application(
    body: SubmitApplicationRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    sender: EmailSender = Depends(get_email_sender),
    application: Application = Depends(require_current_application),
    outbox_runner: Callable[[EmailSender], None] = Depends(get_outbox_runner),
) -> ApplicantApplicationResponse:
    if not body.declaration_accepted:
        raise Problem("declaration_required", detail="Accept the declaration before submitting.")
    lock_application_revision(db, application, body.base_revision)
    require_application_editable(db, application)
    require_matching_email(application, body.answers)
    now = datetime.now(UTC)
    openings = validate_opening_selection(db, application, body.opening_ids, now=now)
    publish_working_copy(db, application, body.answers, openings, submitted_at=now)
    queue_submission_confirmation(db, application)
    acknowledged = get_applicant_application(application, db)
    db.commit()
    background_tasks.add_task(outbox_runner, sender)
    return acknowledged


@router.post("/application/withdraw", response_model=WithdrawApplicationResponse)
def withdraw_applicant_application(
    response: Response,
    application: Application = Depends(require_current_application),
    db: Session = Depends(get_db),
) -> WithdrawApplicationResponse:
    """Withdraw one application and every opening participation from ordinary access."""
    application = lock_application(db, application.id)
    if application is None:
        raise Problem("unauthorized", detail="Application access required.")
    require_application_not_selected(db, application)
    now = datetime.now(UTC)
    cancel_queued_application_emails(db, application.id)
    revoke_application_drafts(db, application.id, now=now)
    if application.submitted_at is None:
        purge_never_submitted_application(db, application)
        db.commit()
        return WithdrawApplicationResponse()

    for state in applicant_opening_states(db, application):
        if state.participating:
            participation = db.scalar(
                select(ApplicationParticipation).where(
                    ApplicationParticipation.application_id == application.id,
                    ApplicationParticipation.opening_id == state.opening.id,
                )
            )
            if participation is not None and participation.withdrawn_at is None:
                participation.withdrawn_at = now

    application.withdrawn_at = now
    application.google_subject = None
    application.working_answers = dict(application.raw_row)
    application.working_content_hash = application.raw_row_hash
    application.working_saved_at = now
    application.working_opening_ids = []
    application.working_revision += 1
    refresh_application_retention(db, application)
    revoke_identity_sessions(
        db,
        identity_kind=PasswordlessIdentityKind.APPLICANT,
        application_id=application.id,
    )
    revoke_identity_magic_links(
        db,
        identity_kind=PasswordlessIdentityKind.APPLICANT,
        application_id=application.id,
    )
    db.commit()
    return WithdrawApplicationResponse()
