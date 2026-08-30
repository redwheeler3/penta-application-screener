"""Applicant-owned pending drafts, identity links, and published applications."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.orm import Session

from app.api.applicant.dependencies import (
    optional_current_application,
)
from app.api.applicant.support import (
    _access_link_response,
    _access_target_is_editable,
    _applicant_link,
    _application_for_access_target,
    _claim_link_target,
    _link_target,
    _pending_copy,
)
from app.api.session_cookie import (
    session_token,
    set_session_cookie,
)
from app.core.config import get_settings
from app.db.models import (
    ApplicantDraft,
    Application,
    PasswordlessIdentityKind,
)
from app.db.session import get_db
from app.schemas.applicant.contracts import (
    AccessLinkRequest,
    AccessLinkResponse,
    OpenAccessLinkRequest,
    RegenerateAccessLinkResponse,
)
from app.services.applicant_drafts import (
    applicant_email_request_allowed,
)
from app.services.email_sender import EmailSender, get_email_sender
from app.services.magic_link_delivery import (
    EmailSendOutcome,
    send_application_unavailable,
    send_email_change_notice,
    send_magic_link,
    send_selected_application_locked,
)
from app.services.passwordless_auth import (
    consume_magic_link,
    create_browser_session,
    revoke_browser_session,
    revoke_identity_magic_links,
    revoke_identity_sessions,
)
from app.services.selected_application import application_is_selected

router = APIRouter()


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
        return AccessLinkResponse(state=claimed.state)
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
        google_disconnected=claimed.google_disconnected,
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
        return RegenerateAccessLinkResponse(
            target_available=False,
            email_sent=False,
            email_status="failed",
            retry_after_seconds=0,
        )
    if not _access_target_is_editable(db, target):
        application = _application_for_access_target(db, target)
        sent = (
            send_selected_application_locked(db, sender, application, now=now)
            if application is not None and application_is_selected(db, application.id)
            else send_application_unavailable(
                db,
                sender,
                link.email,
                application=application,
                now=now,
            )
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
