"""Applicant-owned pending drafts, identity links, and published applications."""

from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import ValidationError
from sqlalchemy import delete as sql_delete
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.applicant_dependencies import (
    optional_current_application,
    require_current_application,
    require_recent_applicant,
)
from app.api.problems import Problem
from app.api.session_cookie import (
    clear_session_cookie,
    session_token,
    set_session_cookie,
)
from app.core.config import get_settings
from app.core.text import normalize_email
from app.core.time import as_utc, pacific_today
from app.db.models import (
    ApplicantDraft,
    ApplicantDraftIntent,
    Application,
    ApplicationParticipation,
    BrowserSession,
    EmailDelivery,
    MagicLinkPurpose,
    MagicLinkToken,
    PasswordlessIdentityKind,
)
from app.db.session import get_db
from app.schemas.applicant_intake import (
    AccessLinkRequest,
    AccessLinkResponse,
    ApplicantApplicationResponse,
    ApplicantOpeningOut,
    ApplicantOpeningsResponse,
    AuthenticatedSubmitApplicationResponse,
    DeleteApplicationResponse,
    EmailChangeRequest,
    EmailChangeResponse,
    GuestSubmissionCheckRequest,
    GuestSubmissionCheckResponse,
    GuestSubmitApplicationRequest,
    GuestSubmitApplicationResponse,
    OpenAccessLinkRequest,
    PendingCopyOut,
    PendingCopyResponse,
    PendingDraftRequest,
    PendingDraftResponse,
    ReconcilePendingCopyRequest,
    RegenerateAccessLinkResponse,
    RequestAccessLinkRequest,
    RequestAccessLinkResponse,
    RevertApplicationRequest,
    SaveApplicationRequest,
    SubmitApplicationRequest,
)
from app.schemas.intake import CanonicalApplicationAnswers, WorkingApplicationAnswers
from app.services.applicant_drafts import (
    applicant_email_request_allowed,
    draft_is_available,
    latest_pending_draft_for_email,
    pending_draft_for_token,
    revoke_other_pending_drafts,
    save_collision_copy,
    save_pending_draft,
)
from app.services.email_delivery import cancel_queued_application_emails
from app.services.email_sender import EmailSender, get_email_sender
from app.services.intake import (
    create_application,
    publish_working_copy,
    save_working_copy,
)
from app.services.magic_link_delivery import (
    EmailSendOutcome,
    send_application_confirmation,
    send_application_deleted,
    send_application_unavailable,
    send_email_change_notice,
    send_magic_link,
)
from app.services.opening_participation import (
    ApplicantOpeningState,
    applicant_opening_states,
    application_is_editable,
    validate_opening_selection,
    validate_working_opening_selection,
)
from app.services.passwordless_auth import (
    consume_magic_link,
    create_browser_session,
    magic_link_for_token,
    revoke_browser_session,
    revoke_identity_magic_links,
    revoke_identity_sessions,
)

router = APIRouter(prefix="/applicant", tags=["applicant intake"])


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


@router.post("/access-links/inspect", response_model=AccessLinkResponse)
def inspect_applicant_access_link(
    body: AccessLinkRequest,
    application: Application | None = Depends(optional_current_application),
    db: Session = Depends(get_db),
) -> AccessLinkResponse:
    link = _applicant_link(db, body.token)
    return _access_link_response(db, link, application)


@router.post("/access-links/open", response_model=AccessLinkResponse)
def open_applicant_access_link(
    body: OpenAccessLinkRequest,
    request: Request,
    response: Response,
    current: Application | None = Depends(optional_current_application),
    db: Session = Depends(get_db),
    sender: EmailSender = Depends(get_email_sender),
) -> AccessLinkResponse:
    inspected = _applicant_link(db, body.token)
    preview = _access_link_response(db, inspected, current)
    if preview.state != "valid":
        return preview
    if preview.switch_required and not body.switch_current:
        return preview

    link = consume_magic_link(
        db,
        body.token,
        identity_kind=PasswordlessIdentityKind.APPLICANT,
        purpose=inspected.purpose,
    )
    if link is None:
        return _access_link_response(db, _applicant_link(db, body.token), current)
    claimed = _claim_link_target(db, link)
    if claimed.application is None:
        db.commit()
        return AccessLinkResponse(state="abandoned")
    target = claimed.application

    current_token = session_token(request, PasswordlessIdentityKind.APPLICANT)
    if claimed.previous_email is not None:
        revoke_identity_sessions(
            db,
            identity_kind=PasswordlessIdentityKind.APPLICANT,
            application_id=target.id,
            except_session_id=link.initiating_session_id,
        )
        revoke_identity_magic_links(
            db,
            identity_kind=PasswordlessIdentityKind.APPLICANT,
            application_id=target.id,
        )
    elif current_token is not None:
        revoke_browser_session(db, current_token)
    issued = create_browser_session(
        db,
        identity_kind=PasswordlessIdentityKind.APPLICANT,
        application_id=target.id,
        reconciliation_draft_id=(
            claimed.reconciliation_draft.id
            if claimed.reconciliation_draft is not None
            else None
        ),
    )
    db.commit()
    set_session_cookie(
        response,
        issued.token,
        identity_kind=PasswordlessIdentityKind.APPLICANT,
        settings=get_settings(),
        persistent=body.remember_device,
    )
    if claimed.previous_email is not None:
        send_email_change_notice(
            db,
            sender,
            target,
            old_email=claimed.previous_email,
        )
    return AccessLinkResponse(
        state=claimed.state,
        purpose=link.purpose,
        current_email=target.primary_email,
        link_email=link.email,
        application_email=target.primary_email,
        application_id=target.id,
        pending_intent=claimed.pending_intent,
        pending_copy=(
            _pending_copy(target, claimed.reconciliation_draft)
            if claimed.reconciliation_draft is not None
            else None
        ),
    )


@router.get("/application/pending-copy", response_model=PendingCopyResponse)
def get_pending_copy(
    request: Request,
    application: Application = Depends(require_current_application),
) -> PendingCopyResponse:
    session: BrowserSession = request.state.passwordless_session
    draft = session.reconciliation_draft
    if not _draft_belongs_to_application(draft, application):
        return PendingCopyResponse()
    return PendingCopyResponse(pending_copy=_pending_copy(application, draft))


@router.post("/application/pending-copy", status_code=status.HTTP_204_NO_CONTENT)
def reconcile_pending_copy(
    body: ReconcilePendingCopyRequest,
    request: Request,
    application: Application = Depends(require_current_application),
    db: Session = Depends(get_db),
) -> Response:
    session: BrowserSession = request.state.passwordless_session
    draft = session.reconciliation_draft
    if not _draft_belongs_to_application(draft, application):
        raise Problem("pending_copy_not_found", detail="These answers are no longer available.")
    if body.choice == "guest":
        _require_application_editable(db, application)
        answers = _draft_answers(draft)
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


@router.post(
    "/access-links/regenerate",
    response_model=RegenerateAccessLinkResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def regenerate_applicant_access_link(
    body: AccessLinkRequest,
    db: Session = Depends(get_db),
    sender: EmailSender = Depends(get_email_sender),
) -> RegenerateAccessLinkResponse:
    now = datetime.now(UTC)
    link = _applicant_link(db, body.token)
    target = _link_target(db, link) if link is not None else None
    if link is None or target is None:
        return RegenerateAccessLinkResponse(
            target_available=False,
            email_sent=False,
            email_status="failed",
            retry_after_seconds=0,
        )
    if not _access_target_is_editable(db, target):
        application = _application_for_access_target(db, target)
        sent = send_application_unavailable(
            db,
            sender,
            link.email,
            application=application,
            now=now,
        )
        return RegenerateAccessLinkResponse(
            email_sent=sent,
            email_status="sent" if sent else "failed",
            retry_after_seconds=get_settings().magic_link_coalesce_seconds,
        )
    can_send = applicant_email_request_allowed(db, link.email, now=now)
    outcome = EmailSendOutcome.RECENT
    if can_send:
        outcome = send_magic_link(
            db,
            sender,
            identity_kind=PasswordlessIdentityKind.APPLICANT,
            purpose=link.purpose,
            email=link.email,
            recipient_id=link.applicant_draft_id or link.application_id or 0,
            application_id=target.id if isinstance(target, Application) else None,
            applicant_draft=target if isinstance(target, ApplicantDraft) else None,
            initiating_session_id=link.initiating_session_id,
            now=now,
            enforce_request_limits=False,
        )
    return RegenerateAccessLinkResponse(
        email_sent=outcome.email_sent,
        email_status=outcome.value,
        retry_after_seconds=get_settings().magic_link_coalesce_seconds,
    )


@router.get("/application", response_model=ApplicantApplicationResponse)
def get_applicant_application(
    application: Application = Depends(require_current_application),
    db: Session = Depends(get_db),
) -> ApplicantApplicationResponse:
    opening_states = applicant_opening_states(db, application, use_working_copy=True)
    submitted_opening_ids = {
        state.opening.id
        for state in applicant_opening_states(db, application)
        if state.selected
    }
    working_opening_ids = {
        state.opening.id for state in opening_states if state.selected
    }
    return ApplicantApplicationResponse(
        application_id=application.id,
        primary_email=application.primary_email,
        pending_email_change=_pending_email_change(db, application.id),
        answers=_stored_answers(application),
        working_saved_at=(
            as_utc(application.working_saved_at)
            if application.working_saved_at is not None
            else None
        ),
        working_revision=application.working_revision,
        submitted=application.submitted_at is not None,
        has_unsubmitted_changes=(
            application.submitted_at is not None
            and (
                application.working_content_hash != application.raw_row_hash
                or working_opening_ids != submitted_opening_ids
            )
        ),
        can_edit=application_is_editable(opening_states),
        openings=[_applicant_opening(state) for state in opening_states],
    )


@router.post(
    "/application/email-change",
    response_model=EmailChangeResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def request_applicant_email_change(
    body: EmailChangeRequest,
    request: Request,
    application: Application = Depends(require_recent_applicant),
    db: Session = Depends(get_db),
    sender: EmailSender = Depends(get_email_sender),
) -> EmailChangeResponse:
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
    pending_email = _pending_email_change(db, application.id)
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
    revoke_identity_magic_links(
        db,
        identity_kind=PasswordlessIdentityKind.APPLICANT,
        application_id=application.id,
        purpose=MagicLinkPurpose.EMAIL_CHANGE,
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/application/reauthentication",
    response_model=RegenerateAccessLinkResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def request_applicant_reauthentication(
    application: Application = Depends(require_current_application),
    db: Session = Depends(get_db),
    sender: EmailSender = Depends(get_email_sender),
) -> RegenerateAccessLinkResponse:
    outcome = send_magic_link(
        db,
        sender,
        identity_kind=PasswordlessIdentityKind.APPLICANT,
        purpose=MagicLinkPurpose.APPLICANT_ACCESS,
        email=application.primary_email,
        recipient_id=application.id,
        application_id=application.id,
    )
    return RegenerateAccessLinkResponse(
        email_sent=outcome.email_sent,
        email_status=outcome.value,
        retry_after_seconds=get_settings().magic_link_coalesce_seconds,
    )


@router.put("/application", response_model=ApplicantApplicationResponse)
def save_applicant_application(
    body: SaveApplicationRequest,
    db: Session = Depends(get_db),
    application: Application = Depends(require_current_application),
) -> ApplicantApplicationResponse:
    _require_application_editable(db, application)
    _require_matching_email(application, body.answers)
    _require_current_revision(application, body.base_revision)
    now = datetime.now(UTC)
    validate_working_opening_selection(db, application, body.opening_ids, now=now)
    save_working_copy(
        application,
        body.answers,
        saved_at=now,
        opening_ids=body.opening_ids,
    )
    db.commit()
    return get_applicant_application(application, db)


@router.post("/application/submit", response_model=AuthenticatedSubmitApplicationResponse)
def submit_applicant_application(
    body: SubmitApplicationRequest,
    db: Session = Depends(get_db),
    sender: EmailSender = Depends(get_email_sender),
    application: Application = Depends(require_current_application),
) -> AuthenticatedSubmitApplicationResponse:
    if not body.declaration_accepted:
        raise Problem("declaration_required", detail="Accept the declaration before submitting.")
    _require_application_editable(db, application)
    _require_matching_email(application, body.answers)
    _require_current_revision(application, body.base_revision)
    now = datetime.now(UTC)
    openings = validate_opening_selection(db, application, body.opening_ids, now=now)
    publish_working_copy(db, application, body.answers, openings, submitted_at=now)
    db.commit()
    email_sent = send_application_confirmation(
        db, sender, application, submitted=True, now=now
    )
    restored = get_applicant_application(application, db)
    return AuthenticatedSubmitApplicationResponse(
        **restored.model_dump(),
        email_sent=email_sent,
        email_status="sent" if email_sent else "failed",
    )


@router.post("/application/revert", response_model=ApplicantApplicationResponse)
def revert_applicant_application(
    body: RevertApplicationRequest,
    application: Application = Depends(require_current_application),
    db: Session = Depends(get_db),
) -> ApplicantApplicationResponse:
    _require_application_editable(db, application)
    _require_current_revision(application, body.base_revision)
    if application.submitted_at is None:
        raise Problem(
            "no_submitted_application",
            detail="This application does not have a submitted copy to restore.",
        )
    selected_ids = [
        state.opening.id
        for state in applicant_opening_states(db, application)
        if state.selected
    ]
    application.working_answers = dict(application.raw_row)
    application.working_content_hash = application.raw_row_hash
    application.working_saved_at = datetime.now(UTC)
    application.working_opening_ids = selected_ids
    application.working_revision += 1
    db.commit()
    return get_applicant_application(application, db)


@router.delete("/application", response_model=DeleteApplicationResponse)
def delete_applicant_application(
    response: Response,
    application: Application = Depends(require_recent_applicant),
    db: Session = Depends(get_db),
    sender: EmailSender = Depends(get_email_sender),
) -> DeleteApplicationResponse:
    """Remove one application and every opening participation from ordinary access."""
    now = datetime.now(UTC)
    cancel_queued_application_emails(db, application.id)
    if application.submitted_at is None:
        email_sent = send_application_deleted(db, sender, application, now=now)
        _purge_never_submitted_application(db, application)
        db.commit()
        clear_session_cookie(response, PasswordlessIdentityKind.APPLICANT)
        return DeleteApplicationResponse(
            email_sent=email_sent,
            email_status="sent" if email_sent else "failed",
        )

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

    application.deleted_at = now
    application.working_answers = dict(application.raw_row)
    application.working_content_hash = application.raw_row_hash
    application.working_saved_at = now
    application.working_opening_ids = []
    application.working_revision += 1
    if application.retention_due_on is None:
        application.retention_due_on = pacific_today(now=now)
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
    email_sent = send_application_deleted(db, sender, application, now=now)
    clear_session_cookie(response, PasswordlessIdentityKind.APPLICANT)
    return DeleteApplicationResponse(
        email_sent=email_sent,
        email_status="sent" if email_sent else "failed",
    )


def _purge_never_submitted_application(db: Session, application: Application) -> None:
    """Physically remove a draft-only application and its access records."""
    draft_ids = select(ApplicantDraft.id).where(ApplicantDraft.application_id == application.id)
    link_ids = select(MagicLinkToken.id).where(
        or_(
            MagicLinkToken.application_id == application.id,
            MagicLinkToken.applicant_draft_id.in_(draft_ids),
        )
    )
    db.execute(
        sql_delete(EmailDelivery).where(
            or_(
                EmailDelivery.application_id == application.id,
                EmailDelivery.applicant_draft_id.in_(draft_ids),
                EmailDelivery.magic_link_token_id.in_(link_ids),
            )
        )
    )
    db.execute(sql_delete(MagicLinkToken).where(MagicLinkToken.id.in_(link_ids)))
    db.execute(sql_delete(ApplicantDraft).where(ApplicantDraft.id.in_(draft_ids)))
    db.execute(
        sql_delete(BrowserSession).where(
            BrowserSession.identity_kind == PasswordlessIdentityKind.APPLICANT,
            BrowserSession.application_id == application.id,
        )
    )
    db.delete(application)


def _applicant_link(db: Session, token: str) -> MagicLinkToken | None:
    access_link = magic_link_for_token(
        db,
        token,
        identity_kind=PasswordlessIdentityKind.APPLICANT,
        purpose=MagicLinkPurpose.APPLICANT_ACCESS,
    )
    if access_link is not None:
        return access_link
    return magic_link_for_token(
        db,
        token,
        identity_kind=PasswordlessIdentityKind.APPLICANT,
        purpose=MagicLinkPurpose.EMAIL_CHANGE,
    )


def _access_link_response(
    db: Session,
    link: MagicLinkToken | None,
    current: Application | None,
    *,
    now: datetime | None = None,
) -> AccessLinkResponse:
    now = now or datetime.now(UTC)
    if link is None:
        return AccessLinkResponse(state="invalid")
    if link.consumed_at is not None:
        state = "used"
    elif link.revoked_at is not None:
        state = "replaced"
    elif as_utc(link.expires_at) <= now:
        state = "expired"
    elif link.applicant_draft is not None and not draft_is_available(link.applicant_draft, now=now):
        state = "abandoned"
    elif link.purpose == MagicLinkPurpose.APPLICANT_ACCESS:
        target = _link_target(db, link)
        if target is None:
            state = "abandoned"
        else:
            state = "valid" if _access_target_is_editable(db, target) else "unavailable"
    else:
        state = "valid"
    return AccessLinkResponse(
        state=state,
        purpose=link.purpose,
        current_email=current.primary_email if current is not None else None,
        link_email=link.email,
        application_email=(link.application.primary_email if link.application is not None else None),
        switch_required=_link_targets_other_application(link, current),
        application_id=current.id if current is not None else None,
        pending_intent=link.applicant_draft.intent if link.applicant_draft is not None else None,
    )


@dataclass(frozen=True)
class _ClaimedApplicantLink:
    application: Application | None
    pending_intent: ApplicantDraftIntent | None = None
    previous_email: str | None = None
    reconciliation_draft: ApplicantDraft | None = None
    state: str = "valid"


def _claim_link_target(db: Session, link: MagicLinkToken) -> _ClaimedApplicantLink:
    if link.purpose == MagicLinkPurpose.EMAIL_CHANGE:
        return _claim_email_change(db, link)
    if link.application_id is not None:
        return _ClaimedApplicantLink(_active_application(db, link.application_id))
    draft = link.applicant_draft
    if draft is None or not draft_is_available(draft):
        return _ClaimedApplicantLink(None)
    application = _active_application(db, draft.application_id)
    if application is None:
        application = db.scalar(
            select(Application).where(
                Application.primary_email == draft.email,
                Application.deleted_at.is_(None),
            )
        )
    if application is not None:
        draft.application_id = application.id
        if _pending_copy_needed(application, draft):
            return _ClaimedApplicantLink(
                application,
                draft.intent,
                reconciliation_draft=draft,
            )
        _resolve_pending_draft(application, draft)
        return _ClaimedApplicantLink(application, draft.intent)
    answers = _draft_answers(draft)
    if answers is None:
        return _ClaimedApplicantLink(None)
    application = create_application(
        db,
        draft.email,
        answers,
        saved_at=as_utc(draft.saved_at),
        opening_ids=draft.working_opening_ids,
    )
    draft.application_id = application.id
    draft.resolved_at = datetime.now(UTC)
    return _ClaimedApplicantLink(application, draft.intent)


def _claim_email_change(db: Session, link: MagicLinkToken) -> _ClaimedApplicantLink:
    application = _active_application(db, link.application_id)
    if application is None:
        return _ClaimedApplicantLink(None)
    conflicting = db.scalar(
        select(Application).where(
            Application.primary_email == link.email,
            Application.id != application.id,
            Application.deleted_at.is_(None),
        )
    )
    if conflicting is not None:
        return _ClaimedApplicantLink(application, state="email_in_use")

    old_email = application.primary_email
    answers = _stored_answers(application)
    if answers is not None:
        updated_applicant = answers.applicant.model_copy(update={"email": link.email})
        updated_answers = answers.model_copy(update={"applicant": updated_applicant})
        save_working_copy(application, updated_answers, saved_at=datetime.now(UTC))
    application.primary_email = link.email
    return _ClaimedApplicantLink(application, previous_email=old_email)


def _link_targets_other_application(
    link: MagicLinkToken, current: Application | None
) -> bool:
    if current is None:
        return False
    target_id = link.application_id
    if target_id is None and link.applicant_draft is not None:
        target_id = link.applicant_draft.application_id
    if target_id is not None:
        return target_id != current.id
    return normalize_email(current.primary_email) != normalize_email(link.email)


def _resolve_pending_draft(application: Application, draft: ApplicantDraft) -> None:
    """Resolve a pending copy that does not require an applicant choice."""
    answers = _draft_answers(draft)
    if answers is not None and _stored_answers(application) is None:
        save_working_copy(
            application,
            answers,
            saved_at=as_utc(draft.saved_at),
            opening_ids=draft.working_opening_ids,
        )
    draft.application_id = application.id
    draft.resolved_at = datetime.now(UTC)


def _pending_copy_needed(application: Application, draft: ApplicantDraft) -> bool:
    saved = _stored_answers(application)
    guest = _draft_answers(draft)
    if saved is None or guest is None:
        return False
    return (
        saved.model_dump(mode="json") != guest.model_dump(mode="json")
        or set(application.working_opening_ids or []) != set(draft.working_opening_ids or [])
    )


def _pending_copy(application: Application, draft: ApplicantDraft) -> PendingCopyOut:
    saved = _stored_answers(application)
    guest = _draft_answers(draft)
    if saved is None or guest is None:
        raise ValueError("pending-copy comparison requires two readable working copies")
    return PendingCopyOut(
        saved_answers=saved,
        saved_opening_ids=list(application.working_opening_ids or []),
        guest_answers=guest,
        guest_opening_ids=list(draft.working_opening_ids or []),
    )


def _draft_belongs_to_application(
    draft: ApplicantDraft | None,
    application: Application,
) -> bool:
    return bool(
        draft is not None
        and draft.application_id == application.id
        and draft_is_available(draft)
    )


def _link_target(db: Session, link: MagicLinkToken) -> Application | ApplicantDraft | None:
    if link.application_id is not None:
        return _active_application(db, link.application_id)
    draft = link.applicant_draft
    if draft is None:
        return None
    if draft.resolved_at is not None and draft.application_id is not None:
        return _active_application(db, draft.application_id)
    return draft if draft_is_available(draft) else None


def _application_for_access_target(
    db: Session, target: Application | ApplicantDraft
) -> Application | None:
    if isinstance(target, Application):
        return target
    application = _active_application(db, target.application_id)
    if application is not None:
        return application
    return db.scalar(
        select(Application).where(
            Application.primary_email == target.email,
            Application.deleted_at.is_(None),
        )
    )


def _access_target_is_editable(
    db: Session, target: Application | ApplicantDraft
) -> bool:
    application = _application_for_access_target(db, target)
    if application is not None:
        return application_is_editable(applicant_opening_states(db, application))
    return _new_applications_are_open(db)


def _active_application(db: Session, application_id: int | None) -> Application | None:
    application = db.get(Application, application_id) if application_id is not None else None
    return application if application is not None and application.deleted_at is None else None


def _draft_answers(draft: ApplicantDraft | None) -> WorkingApplicationAnswers | None:
    if draft is None or draft.working_answers is None:
        return None
    try:
        return WorkingApplicationAnswers.model_validate(draft.working_answers)
    except ValidationError:
        return None


def _pending_email_change(db: Session, application_id: int) -> str | None:
    now = datetime.now(UTC)
    return db.scalar(
        select(MagicLinkToken.email)
        .where(
            MagicLinkToken.application_id == application_id,
            MagicLinkToken.purpose == MagicLinkPurpose.EMAIL_CHANGE,
            MagicLinkToken.consumed_at.is_(None),
            MagicLinkToken.revoked_at.is_(None),
            MagicLinkToken.expires_at > now,
        )
        .order_by(MagicLinkToken.created_at.desc())
    )
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


def _require_new_applications_open(db: Session) -> None:
    if not _new_applications_are_open(db):
        raise Problem("applications_closed", detail="Applications are not currently open.")


def _new_applications_are_open(db: Session) -> bool:
    return any(state.can_select for state in applicant_opening_states(db, None))


def _require_application_editable(db: Session, application: Application) -> None:
    if not application_is_editable(applicant_opening_states(db, application)):
        raise Problem("applications_locked", detail="This application cannot be edited right now.")


def _stored_answers(application: Application) -> WorkingApplicationAnswers | None:
    stored = application.working_answers
    if stored is None and "applicant" in (application.raw_row or {}):
        stored = application.raw_row
    if stored is None:
        return None
    try:
        return WorkingApplicationAnswers.model_validate(stored)
    except ValidationError:
        return None


def _require_matching_email(
    application: Application,
    answers: WorkingApplicationAnswers | CanonicalApplicationAnswers,
) -> None:
    if normalize_email(str(answers.applicant.email)) != normalize_email(
        application.primary_email
    ):
        raise Problem(
            "verified_email_required",
            detail="Use Change email address to update your application email.",
        )


def _require_current_revision(application: Application, base_revision: int | None) -> None:
    if base_revision != application.working_revision:
        raise Problem(
            "stale_application",
            detail=(
                "This application was saved in another tab or browser. "
                "Reload the latest saved copy before continuing."
            ),
        )
