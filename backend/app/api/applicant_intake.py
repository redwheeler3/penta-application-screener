"""Applicant-owned pending drafts, identity links, and published applications."""

from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.applicant_dependencies import (
    optional_current_application,
    require_current_application,
    require_recent_applicant,
)
from app.api.problems import Problem
from app.api.session_cookie import session_token, set_session_cookie
from app.core.config import get_settings
from app.core.text import normalize_email
from app.core.time import as_utc
from app.db.models import (
    ApplicantDraft,
    ApplicantDraftIntent,
    Application,
    MagicLinkPurpose,
    MagicLinkToken,
    Opening,
    OpeningStatus,
    PasswordlessIdentityKind,
)
from app.db.session import get_db
from app.schemas.applicant_intake import (
    AccessLinkRequest,
    AccessLinkResponse,
    ApplicantApplicationResponse,
    EmailChangeRequest,
    EmailChangeResponse,
    OpenAccessLinkRequest,
    PendingDraftRequest,
    PendingDraftResponse,
    RegenerateAccessLinkResponse,
    RequestAccessLinkRequest,
    RequestAccessLinkResponse,
    SaveApplicationRequest,
    SubmitApplicationRequest,
)
from app.schemas.intake import CanonicalApplicationAnswers, WorkingApplicationAnswers
from app.services.applicant_drafts import (
    applicant_email_request_allowed,
    draft_is_available,
    latest_pending_draft_for_email,
    pending_draft_for_token,
    save_pending_draft,
)
from app.services.email_sender import EmailSender, get_email_sender
from app.services.intake import (
    create_application,
    publish_working_copy,
    save_working_copy,
)
from app.services.magic_link_delivery import (
    send_application_confirmation,
    send_email_change_notice,
    send_magic_link,
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


@router.post("/drafts", response_model=PendingDraftResponse, status_code=status.HTTP_202_ACCEPTED)
def save_applicant_draft(
    body: PendingDraftRequest,
    db: Session = Depends(get_db),
    sender: EmailSender = Depends(get_email_sender),
) -> PendingDraftResponse:
    now = datetime.now(UTC)
    saved = save_pending_draft(
        db,
        answers=body.answers,
        intent=body.intent,
        draft_token=body.draft_token,
        now=now,
    )
    can_send = applicant_email_request_allowed(db, saved.record.email, now=now)
    sent = can_send and send_magic_link(
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
        email_sent=sent,
        retry_after_seconds=get_settings().magic_link_coalesce_seconds,
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
        _require_matching_email(current, body.answers)
        save_working_copy(current, body.answers, saved_at=now)
        target: Application | ApplicantDraft = current
    else:
        draft = latest_pending_draft_for_email(db, email, now=now)
        application = db.scalar(
            select(Application).where(
                Application.primary_email == email,
                Application.deleted_at.is_(None),
            )
        )
        if draft is not None:
            target = draft
        elif application is not None:
            target = application
        else:
            saved = save_pending_draft(
                db,
                answers=body.answers,
                intent=ApplicantDraftIntent.SAVE,
                now=now,
            )
            target = saved.record

    can_send = applicant_email_request_allowed(db, email, now=now)
    if can_send:
        send_magic_link(
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

    return RequestAccessLinkResponse(current_answers_saved=current is not None)


@router.post("/access-links/inspect", response_model=AccessLinkResponse)
def inspect_applicant_access_link(
    body: AccessLinkRequest,
    application: Application | None = Depends(optional_current_application),
    db: Session = Depends(get_db),
) -> AccessLinkResponse:
    link = _applicant_link(db, body.token)
    return _access_link_response(link, application)


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
    preview = _access_link_response(inspected, current)
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
        return _access_link_response(_applicant_link(db, body.token), current)
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
    )


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
        return RegenerateAccessLinkResponse(email_sent=False, retry_after_seconds=0)
    can_send = applicant_email_request_allowed(db, link.email, now=now)
    sent = can_send and send_magic_link(
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
        email_sent=sent,
        retry_after_seconds=get_settings().magic_link_coalesce_seconds,
    )


@router.get("/application", response_model=ApplicantApplicationResponse)
def get_applicant_application(
    application: Application = Depends(require_current_application),
    db: Session = Depends(get_db),
) -> ApplicantApplicationResponse:
    return ApplicantApplicationResponse(
        application_id=application.id,
        primary_email=application.primary_email,
        pending_email_change=_pending_email_change(db, application.id),
        answers=_stored_answers(application),
        submitted=application.submitted_at is not None,
        has_unsubmitted_changes=(
            application.submitted_at is not None
            and application.working_content_hash != application.raw_row_hash
        ),
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
    sent = send_magic_link(
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
        email_sent=sent,
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
    sent = send_magic_link(
        db,
        sender,
        identity_kind=PasswordlessIdentityKind.APPLICANT,
        purpose=MagicLinkPurpose.APPLICANT_ACCESS,
        email=application.primary_email,
        recipient_id=application.id,
        application_id=application.id,
    )
    return RegenerateAccessLinkResponse(
        email_sent=sent,
        retry_after_seconds=get_settings().magic_link_coalesce_seconds,
    )


@router.put("/application", response_model=ApplicantApplicationResponse)
def save_applicant_application(
    body: SaveApplicationRequest,
    db: Session = Depends(get_db),
    application: Application = Depends(require_current_application),
) -> ApplicantApplicationResponse:
    _require_matching_email(application, body.answers)
    save_working_copy(application, body.answers, saved_at=datetime.now(UTC))
    db.commit()
    return get_applicant_application(application, db)


@router.post("/application/submit", response_model=ApplicantApplicationResponse)
def submit_applicant_application(
    body: SubmitApplicationRequest,
    db: Session = Depends(get_db),
    sender: EmailSender = Depends(get_email_sender),
    application: Application = Depends(require_current_application),
) -> ApplicantApplicationResponse:
    if not body.declaration_accepted:
        raise Problem("declaration_required", detail="Accept the declaration before submitting.")
    _require_matching_email(application, body.answers)
    now = datetime.now(UTC)
    opening = _active_opening(db, now=now)
    publish_working_copy(db, application, body.answers, opening, submitted_at=now)
    db.commit()
    send_application_confirmation(db, sender, application, submitted=True, now=now)
    return get_applicant_application(application, db)


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
        _resolve_pending_draft(application, draft)
        return _ClaimedApplicantLink(application, draft.intent)
    answers = _draft_answers(draft)
    if answers is None:
        return _ClaimedApplicantLink(None)
    application = create_application(db, draft.email, answers, saved_at=as_utc(draft.saved_at))
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
    """Keep the newest whole working copy after the email owner claims a draft."""
    draft_saved_at = as_utc(draft.saved_at)
    application_saved_at = (
        as_utc(application.working_saved_at)
        if application.working_saved_at is not None
        else None
    )
    answers = _draft_answers(draft)
    if answers is not None and (
        application_saved_at is None or draft_saved_at >= application_saved_at
    ):
        save_working_copy(application, answers, saved_at=draft_saved_at)
    draft.application_id = application.id
    draft.resolved_at = datetime.now(UTC)


def _link_target(db: Session, link: MagicLinkToken) -> Application | ApplicantDraft | None:
    if link.application_id is not None:
        return _active_application(db, link.application_id)
    draft = link.applicant_draft
    if draft is None:
        return None
    if draft.resolved_at is not None and draft.application_id is not None:
        return _active_application(db, draft.application_id)
    return draft if draft_is_available(draft) else None


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
def _active_opening(db: Session, *, now: datetime) -> Opening:
    openings = [
        opening
        for opening in db.scalars(
            select(Opening)
            .where(Opening.status == OpeningStatus.OPEN)
            .order_by(Opening.application_deadline.desc())
        )
        if as_utc(opening.application_deadline) > now
    ]
    if not openings:
        raise Problem("applications_closed", detail="Applications are not currently open.")
    if len(openings) > 1:
        raise Problem(
            "opening_selection_required",
            detail="Choose which opening you want this application considered for.",
        )
    return openings[0]


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
            detail="Changing the primary email requires a new access link.",
        )
