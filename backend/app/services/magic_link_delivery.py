"""Issue and deliver passwordless access links through the shared email ledger."""

from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.text import normalize_email
from app.core.time import pacific_today
from app.db.models import (
    ApplicantDraft,
    Application,
    EmailDelivery,
    EmailDeliveryState,
    MagicLinkPurpose,
    PasswordlessIdentityKind,
)
from app.services.auth_email import (
    application_confirmation_email,
    application_unavailable_email,
    email_change_notice_email,
    magic_link_email,
    selected_application_locked_email,
)
from app.services.email_delivery import deliver_email
from app.services.email_sender import EmailSender
from app.services.passwordless_auth import (
    issue_magic_link,
    magic_link_request_allowed,
)
from app.services.vacancy_notifications import application_confirmation_timelines


class EmailSendOutcome(StrEnum):
    SENT = "sent"
    RECENT = "recent"
    FAILED = "failed"

    @property
    def email_sent(self) -> bool:
        return self == EmailSendOutcome.SENT


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
) -> EmailSendOutcome:
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
        return EmailSendOutcome.RECENT
    _supersede_queued_credentials(
        db,
        purpose=purpose,
        application_id=application_id,
        applicant_draft_id=applicant_draft.id if applicant_draft is not None else None,
        user_id=user_id,
    )
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
    delivered = deliver_email(
        db,
        sender,
        message,
        recipient_kind=identity_kind,
        application_id=application_id,
        applicant_draft=applicant_draft,
        user_id=user_id,
        magic_link_token=issued.record,
        retry_intent={
            "type": "magic_link",
            "purpose": purpose.value,
            "remember_device": remember_device,
            "initiating_session_id": initiating_session_id,
        },
        now=now,
    )
    return EmailSendOutcome.SENT if delivered else EmailSendOutcome.FAILED


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
    _supersede_queued_credentials(
        db,
        purpose=MagicLinkPurpose.APPLICANT_ACCESS,
        application_id=application.id,
    )
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
        opening_timelines=(
            application_confirmation_timelines(db, application.id)
            if submitted
            else []
        ),
        settings=get_settings(),
    )
    return deliver_email(
        db,
        sender,
        message,
        recipient_kind=PasswordlessIdentityKind.APPLICANT,
        application_id=application.id,
        magic_link_token=issued.record,
        retry_intent={
            "type": "application_confirmation",
            "submitted": submitted,
        },
        now=now,
    )


def _supersede_queued_credentials(
    db: Session,
    *,
    purpose: MagicLinkPurpose,
    application_id: int | None = None,
    applicant_draft_id: int | None = None,
    user_id: int | None = None,
) -> None:
    deliveries = db.scalars(
        select(EmailDelivery).where(
            EmailDelivery.state == EmailDeliveryState.QUEUED,
            EmailDelivery.application_id == application_id,
            EmailDelivery.applicant_draft_id == applicant_draft_id,
            EmailDelivery.user_id == user_id,
        )
    ).all()
    for delivery in deliveries:
        intent = delivery.retry_intent or {}
        intent_purpose = (
            MagicLinkPurpose.APPLICANT_ACCESS.value
            if intent.get("type") == "application_confirmation"
            else intent.get("purpose")
        )
        if intent_purpose != purpose.value:
            continue
        delivery.state = EmailDeliveryState.FAILED
        delivery.retry_intent = None
        delivery.quota_blocked = False
        delivery.last_error_code = "Superseded"
    db.commit()


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
        retry_intent={
            "type": "email_change_notice",
            "old_email": old_email,
        },
        now=now,
    )


def send_application_unavailable(
    db: Session,
    sender: EmailSender,
    email: str,
    *,
    application: Application | None = None,
    now: datetime | None = None,
) -> bool:
    now = now or datetime.now(UTC)
    recipient_email = application.primary_email if application is not None else email
    recipient_key = (
        f"application:{application.id}"
        if application is not None
        else f"email:{sha256(normalize_email(email).encode()).hexdigest()[:24]}"
    )
    return deliver_email(
        db,
        sender,
        application_unavailable_email(
            application_id=application.id if application is not None else None,
            email=recipient_email,
        ),
        recipient_kind=PasswordlessIdentityKind.APPLICANT,
        application_id=application.id if application is not None else None,
        idempotency_key=(
            f"application-unavailable:{recipient_key}:{pacific_today(now=now).isoformat()}"
        ),
        retry_intent={"type": "application_unavailable"},
        now=now,
    )


def send_selected_application_locked(
    db: Session,
    sender: EmailSender,
    application: Application,
    *,
    now: datetime | None = None,
) -> bool:
    now = now or datetime.now(UTC)
    return deliver_email(
        db,
        sender,
        selected_application_locked_email(
            application_id=application.id,
            email=application.primary_email,
        ),
        recipient_kind=PasswordlessIdentityKind.APPLICANT,
        application_id=application.id,
        idempotency_key=(
            f"application-selected-locked:{application.id}:"
            f"{pacific_today(now=now).isoformat()}"
        ),
        retry_intent={"type": "application_selected_locked"},
        now=now,
    )
