"""Passwordless request and credential-exchange endpoints for both application hosts."""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.orm import Session

from app.api.applicant.dependencies import optional_current_application
from app.api.auth import serialize_user
from app.api.dependencies import optional_current_user
from app.api.problems import Problem
from app.api.session_cookie import (
    clear_session_cookie,
    session_token,
    set_session_cookie,
)
from app.core.config import get_settings
from app.core.text import normalize_email
from app.core.time import as_utc
from app.db.models import (
    Application,
    MagicLinkPurpose,
    MagicLinkToken,
    PasswordlessIdentityKind,
    User,
)
from app.db.session import get_db
from app.schemas.auth import LogoutResponse
from app.schemas.passwordless_auth import (
    ApplicantMeResponse,
    CommitteeLinkInspectionResponse,
    CommitteeSignInResponse,
    MagicLinkConsumeRequest,
    MagicLinkRequest,
    MagicLinkRequestResponse,
)
from app.services.allowlist import get_entry
from app.services.email_sender import EmailSender, get_email_sender
from app.services.magic_link_delivery import send_magic_link
from app.services.passwordless_auth import (
    consume_magic_link,
    create_browser_session,
    magic_link_for_token,
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
        send_magic_link(
            db,
            sender,
            identity_kind=PasswordlessIdentityKind.COMMITTEE,
            purpose=MagicLinkPurpose.COMMITTEE_ACCESS,
            email=user.email,
            recipient_id=user.id,
            user_id=user.id,
            remember_device=body.remember_device,
        )
    return MagicLinkRequestResponse()


@router.post(
    "/auth/magic-link/consume",
    response_model=CommitteeSignInResponse,
)
def consume_committee_magic_link(
    body: MagicLinkConsumeRequest,
    request: Request,
    response: Response,
    current: User | None = Depends(optional_current_user),
    db: Session = Depends(get_db),
) -> CommitteeSignInResponse:
    inspected = _committee_link(db, body.token)
    target = _active_committee_user(db, inspected)
    if target is None:
        raise _invalid_magic_link()
    if current is not None and current.id != target.id and not body.switch_current:
        raise Problem(
            "session_switch_required",
            status=status.HTTP_409_CONFLICT,
            detail="Choose which committee account to use before signing in.",
        )
    link = consume_magic_link(
        db,
        body.token,
        identity_kind=PasswordlessIdentityKind.COMMITTEE,
        purpose=MagicLinkPurpose.COMMITTEE_ACCESS,
    )
    user = _active_committee_user(db, link)
    if user is None:
        db.commit()
        raise _invalid_magic_link()

    current_token = session_token(request, PasswordlessIdentityKind.COMMITTEE)
    if current_token is not None:
        revoke_browser_session(db, current_token)
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
        persistent=link.remember_device,
    )
    return CommitteeSignInResponse(user=serialize_user(user))


@router.post(
    "/auth/magic-link/inspect",
    response_model=CommitteeLinkInspectionResponse,
)
def inspect_committee_magic_link(
    body: MagicLinkConsumeRequest,
    current: User | None = Depends(optional_current_user),
    db: Session = Depends(get_db),
) -> CommitteeLinkInspectionResponse:
    link = _committee_link(db, body.token)
    target = _active_committee_user(db, link)
    if link is None or target is None:
        return CommitteeLinkInspectionResponse(
            state="invalid",
            current_user=serialize_user(current) if current is not None else None,
        )
    if link.consumed_at is not None:
        state = "used"
    elif link.revoked_at is not None:
        state = "replaced"
    elif as_utc(link.expires_at) <= datetime.now(UTC):
        state = "expired"
    else:
        state = "valid"
    return CommitteeLinkInspectionResponse(
        state=state,
        current_user=serialize_user(current) if current is not None else None,
        link_email=target.email,
        switch_required=current is not None and current.id != target.id,
    )


@router.post(
    "/auth/magic-link/regenerate",
    response_model=MagicLinkRequestResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def regenerate_committee_magic_link(
    body: MagicLinkConsumeRequest,
    db: Session = Depends(get_db),
    sender: EmailSender = Depends(get_email_sender),
) -> MagicLinkRequestResponse:
    link = _committee_link(db, body.token)
    user = _active_committee_user(db, link)
    now = datetime.now(UTC)
    can_send = (
        link is not None
        and user is not None
        and magic_link_request_allowed(
            db,
            identity_kind=PasswordlessIdentityKind.COMMITTEE,
            purpose=MagicLinkPurpose.COMMITTEE_ACCESS,
            user_id=user.id,
            email=user.email,
            now=now,
            coalesce_window=timedelta(0),
        )
    )
    if can_send and link is not None and user is not None:
        send_magic_link(
            db,
            sender,
            identity_kind=PasswordlessIdentityKind.COMMITTEE,
            purpose=MagicLinkPurpose.COMMITTEE_ACCESS,
            email=user.email,
            recipient_id=user.id,
            user_id=user.id,
            remember_device=link.remember_device,
            now=now,
            enforce_request_limits=False,
        )
    return MagicLinkRequestResponse()


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


def _committee_link(db: Session, token: str) -> MagicLinkToken | None:
    return magic_link_for_token(
        db,
        token,
        identity_kind=PasswordlessIdentityKind.COMMITTEE,
        purpose=MagicLinkPurpose.COMMITTEE_ACCESS,
    )


def _active_committee_user(db: Session, link: MagicLinkToken | None) -> User | None:
    user = db.get(User, link.user_id) if link is not None and link.user_id is not None else None
    entry = get_entry(db, user.email) if user is not None else None
    if user is None or not user.is_active or entry is None or entry.role != user.role:
        return None
    return user
