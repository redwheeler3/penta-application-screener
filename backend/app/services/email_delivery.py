"""Persist provider-neutral delivery outcomes without retaining message contents or addresses."""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.db.models import (
    ApplicantDraft,
    EmailDelivery,
    EmailDeliveryState,
    MagicLinkToken,
    PasswordlessIdentityKind,
)
from app.services.email_sender import EmailSender, OutboundEmail


def deliver_email(
    db: Session,
    sender: EmailSender,
    message: OutboundEmail,
    *,
    recipient_kind: PasswordlessIdentityKind,
    application_id: int | None = None,
    user_id: int | None = None,
    magic_link_token: MagicLinkToken | None = None,
    applicant_draft: ApplicantDraft | None = None,
    now: datetime | None = None,
) -> bool:
    """Attempt one send and durably record its provider outcome."""
    now = now or datetime.now(UTC)
    delivery = EmailDelivery(
        message_kind=message.kind,
        recipient_kind=recipient_kind,
        application_id=application_id,
        user_id=user_id,
        magic_link_token_id=magic_link_token.id if magic_link_token is not None else None,
        applicant_draft_id=applicant_draft.id if applicant_draft is not None else None,
        state=EmailDeliveryState.QUEUED,
        attempt_count=1,
        last_attempt_at=now,
    )
    db.add(delivery)
    try:
        delivery.provider_message_id = sender.send(message)
        delivery.state = EmailDeliveryState.ACCEPTED
    except Exception as error:
        delivery.state = EmailDeliveryState.FAILED
        delivery.last_error_code = type(error).__name__[:120]
        if magic_link_token is not None:
            magic_link_token.revoked_at = now
    db.commit()
    return delivery.state == EmailDeliveryState.ACCEPTED
