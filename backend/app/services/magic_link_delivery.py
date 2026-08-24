"""Issue and deliver passwordless access links through the shared email ledger."""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import (
    ApplicantDraft,
    Application,
    MagicLinkPurpose,
    PasswordlessIdentityKind,
)
from app.services.auth_email import (
    application_confirmation_email,
    email_change_notice_email,
    magic_link_email,
)
from app.services.email_delivery import deliver_email
from app.services.email_sender import EmailSender
from app.services.passwordless_auth import (
    issue_magic_link,
    magic_link_request_allowed,
)


def send_magic_link(
    db: Session,
    sender: EmailSender,
    *,
    identity_kind: PasswordlessIdentityKind,
    purpose: MagicLinkPurpose,
    email: str,
    recipient_id: int,
    application_id: int | None = None,
    applicant_draft: ApplicantDraft | None = None,
    user_id: int | None = None,
    now: datetime | None = None,
    enforce_request_limits: bool = True,
    remember_device: bool = False,
    initiating_session_id: int | None = None,
) -> bool:
    now = now or datetime.now(UTC)
    if enforce_request_limits and not magic_link_request_allowed(
        db,
        identity_kind=identity_kind,
        purpose=purpose,
        application_id=application_id,
        applicant_draft_id=applicant_draft.id if applicant_draft is not None else None,
        user_id=user_id,
        email=email,
        now=now,
    ):
        return False
    issued = issue_magic_link(
        db,
        identity_kind=identity_kind,
        email=email,
        purpose=purpose,
        application_id=application_id,
        applicant_draft_id=applicant_draft.id if applicant_draft is not None else None,
        user_id=user_id,
        now=now,
        remember_device=remember_device,
        initiating_session_id=initiating_session_id,
    )
    message = magic_link_email(
        identity_kind=identity_kind,
        purpose=purpose,
        recipient_id=recipient_id,
        email=email,
        token=issued.token,
        settings=get_settings(),
    )
    return deliver_email(
        db,
        sender,
        message,
        recipient_kind=identity_kind,
        application_id=application_id,
        applicant_draft=applicant_draft,
        user_id=user_id,
        magic_link_token=issued.record,
        now=now,
    )


def send_application_confirmation(
    db: Session,
    sender: EmailSender,
    application: Application,
    *,
    submitted: bool,
    now: datetime | None = None,
) -> bool:
    """Send a fresh return credential after a deliberate save or publication."""
    now = now or datetime.now(UTC)
    issued = issue_magic_link(
        db,
        identity_kind=PasswordlessIdentityKind.APPLICANT,
        email=application.primary_email,
        purpose=MagicLinkPurpose.APPLICANT_ACCESS,
        application_id=application.id,
        now=now,
    )
    message = application_confirmation_email(
        application_id=application.id,
        email=application.primary_email,
        token=issued.token,
        submitted=submitted,
        settings=get_settings(),
    )
    return deliver_email(
        db,
        sender,
        message,
        recipient_kind=PasswordlessIdentityKind.APPLICANT,
        application_id=application.id,
        magic_link_token=issued.record,
        now=now,
    )


def send_email_change_notice(
    db: Session,
    sender: EmailSender,
    application: Application,
    *,
    old_email: str,
    now: datetime | None = None,
) -> bool:
    """Notify the previous address after a verified identity change."""
    now = now or datetime.now(UTC)
    message = email_change_notice_email(
        application_id=application.id,
        old_email=old_email,
        new_email=application.primary_email,
    )
    return deliver_email(
        db,
        sender,
        message,
        recipient_kind=PasswordlessIdentityKind.APPLICANT,
        application_id=application.id,
        now=now,
    )
