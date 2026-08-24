"""Passwordless request and credential-exchange endpoints for both application hosts."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.applicant_dependencies import optional_current_application
from app.api.auth import serialize_user
from app.api.problems import Problem
from app.api.session_cookie import (
    clear_session_cookie,
    session_token,
    set_session_cookie,
)
from app.core.config import get_settings
from app.core.text import normalize_email
from app.db.models import Application, MagicLinkPurpose, PasswordlessIdentityKind, User
from app.db.session import get_db
from app.schemas.auth import LogoutResponse
from app.schemas.passwordless_auth import (
    ApplicantMeResponse,
    ApplicantSignInResponse,
    CommitteeSignInResponse,
    MagicLinkConsumeRequest,
    MagicLinkRequest,
    MagicLinkRequestResponse,
)
from app.services.allowlist import get_entry
from app.services.auth_email import magic_link_email
from app.services.email_delivery import deliver_email
from app.services.email_sender import EmailSender, get_email_sender
from app.services.passwordless_auth import (
    consume_magic_link,
    create_browser_session,
    issue_magic_link,
    magic_link_request_allowed,
    revoke_browser_session,
)
from app.services.users import upsert_committee_user

router = APIRouter(tags=["passwordless auth"])


@router.post(
    "/auth/magic-link",
    response_model=MagicLinkRequestResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def request_committee_magic_link(
    body: MagicLinkRequest,
    db: Session = Depends(get_db),
    sender: EmailSender = Depends(get_email_sender),
) -> MagicLinkRequestResponse:
    email = normalize_email(body.email)
    entry = get_entry(db, email)
    if entry is not None:
        user = upsert_committee_user(db, email=email, role=entry.role)
        _send_magic_link(
            db,
            sender,
            identity_kind=PasswordlessIdentityKind.COMMITTEE,
            purpose=MagicLinkPurpose.COMMITTEE_ACCESS,
            email=user.email,
            recipient_id=user.id,
            user_id=user.id,
        )
    return MagicLinkRequestResponse()


@router.post(
    "/applicant/auth/magic-link",
    response_model=MagicLinkRequestResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def request_applicant_magic_link(
    body: MagicLinkRequest,
    db: Session = Depends(get_db),
    sender: EmailSender = Depends(get_email_sender),
) -> MagicLinkRequestResponse:
    email = normalize_email(body.email)
    application = db.scalar(
        select(Application).where(
            Application.primary_email == email,
            Application.deleted_at.is_(None),
        )
    )
    if application is not None:
        _send_magic_link(
            db,
            sender,
            identity_kind=PasswordlessIdentityKind.APPLICANT,
            purpose=MagicLinkPurpose.APPLICANT_ACCESS,
            email=application.primary_email,
            recipient_id=application.id,
            application_id=application.id,
        )
    return MagicLinkRequestResponse()


@router.post(
    "/auth/magic-link/consume",
    response_model=CommitteeSignInResponse,
)
def consume_committee_magic_link(
    body: MagicLinkConsumeRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> CommitteeSignInResponse:
    link = consume_magic_link(
        db,
        body.token,
        identity_kind=PasswordlessIdentityKind.COMMITTEE,
        purpose=MagicLinkPurpose.COMMITTEE_ACCESS,
    )
    user = db.get(User, link.user_id) if link is not None and link.user_id is not None else None
    entry = get_entry(db, user.email) if user is not None else None
    if user is None or not user.is_active or entry is None or entry.role != user.role:
        db.commit()
        raise _invalid_magic_link()

    issued_session = create_browser_session(
        db,
        identity_kind=PasswordlessIdentityKind.COMMITTEE,
        user_id=user.id,
    )
    db.commit()
    set_session_cookie(
        response,
        issued_session.token,
        identity_kind=PasswordlessIdentityKind.COMMITTEE,
        settings=get_settings(),
    )
    return CommitteeSignInResponse(user=serialize_user(user))


@router.post(
    "/applicant/auth/magic-link/consume",
    response_model=ApplicantSignInResponse,
)
def consume_applicant_magic_link(
    body: MagicLinkConsumeRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> ApplicantSignInResponse:
    link = consume_magic_link(
        db,
        body.token,
        identity_kind=PasswordlessIdentityKind.APPLICANT,
        purpose=MagicLinkPurpose.APPLICANT_ACCESS,
    )
    application = (
        db.get(Application, link.application_id)
        if link is not None and link.application_id is not None
        else None
    )
    if application is None or application.deleted_at is not None:
        db.commit()
        raise _invalid_magic_link()

    issued_session = create_browser_session(
        db,
        identity_kind=PasswordlessIdentityKind.APPLICANT,
        application_id=application.id,
    )
    db.commit()
    set_session_cookie(
        response,
        issued_session.token,
        identity_kind=PasswordlessIdentityKind.APPLICANT,
        settings=get_settings(),
    )
    return ApplicantSignInResponse(application_id=application.id)


@router.get("/applicant/auth/me", response_model=ApplicantMeResponse)
def get_current_applicant(
    application: Application | None = Depends(optional_current_application),
) -> ApplicantMeResponse:
    return ApplicantMeResponse(
        application_id=application.id if application is not None else None
    )


@router.post("/applicant/auth/logout", response_model=LogoutResponse)
def logout_applicant(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> LogoutResponse:
    token = session_token(request, PasswordlessIdentityKind.APPLICANT)
    if token is not None:
        revoke_browser_session(db, token)
        db.commit()
    clear_session_cookie(response, PasswordlessIdentityKind.APPLICANT)
    return LogoutResponse(ok=True)


def _invalid_magic_link() -> Problem:
    return Problem(
        "invalid_magic_link",
        detail="This sign-in link is invalid or has expired. Request a new one.",
    )


def _send_magic_link(
    db: Session,
    sender: EmailSender,
    *,
    identity_kind: PasswordlessIdentityKind,
    purpose: MagicLinkPurpose,
    email: str,
    recipient_id: int,
    application_id: int | None = None,
    user_id: int | None = None,
) -> None:
    now = datetime.now(UTC)
    if not magic_link_request_allowed(
        db,
        identity_kind=identity_kind,
        purpose=purpose,
        application_id=application_id,
        user_id=user_id,
        now=now,
    ):
        return
    issued = issue_magic_link(
        db,
        identity_kind=identity_kind,
        email=email,
        purpose=purpose,
        application_id=application_id,
        user_id=user_id,
        now=now,
    )
    message = magic_link_email(
        identity_kind=identity_kind,
        recipient_id=recipient_id,
        email=email,
        token=issued.token,
        settings=get_settings(),
    )
    deliver_email(
        db,
        sender,
        message,
        recipient_kind=identity_kind,
        application_id=application_id,
        user_id=user_id,
        magic_link_token=issued.record,
        now=now,
    )
