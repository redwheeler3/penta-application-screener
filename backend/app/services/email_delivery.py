"""Persist provider-neutral delivery outcomes without retaining message contents or addresses."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
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
    idempotency_key: str | None = None,
    now: datetime | None = None,
) -> bool:
    """Attempt one send and durably record its provider outcome."""
    now = now or datetime.now(UTC)
    delivery = _reserve_delivery(
        db,
        message,
        recipient_kind=recipient_kind,
        application_id=application_id,
        user_id=user_id,
        magic_link_token=magic_link_token,
        applicant_draft=applicant_draft,
        idempotency_key=idempotency_key,
        now=now,
    )
    if delivery is None:
        existing = _delivery_for_key(db, idempotency_key)
        return existing is not None and existing.state == EmailDeliveryState.ACCEPTED
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


def _reserve_delivery(
    db: Session,
    message: OutboundEmail,
    *,
    recipient_kind: PasswordlessIdentityKind,
    application_id: int | None,
    user_id: int | None,
    magic_link_token: MagicLinkToken | None,
    applicant_draft: ApplicantDraft | None,
    idempotency_key: str | None,
    now: datetime,
) -> EmailDelivery | None:
    existing = _delivery_for_key(db, idempotency_key)
    if existing is not None:
        if existing.state == EmailDeliveryState.ACCEPTED:
            return None
        last_attempt_at = existing.last_attempt_at
        if last_attempt_at is not None and last_attempt_at.tzinfo is None:
            last_attempt_at = last_attempt_at.replace(tzinfo=UTC)
        if (
            existing.state == EmailDeliveryState.QUEUED
            and last_attempt_at is not None
            and last_attempt_at > now - timedelta(minutes=10)
        ):
            return None
        existing.state = EmailDeliveryState.QUEUED
        existing.attempt_count += 1
        existing.last_attempt_at = now
        existing.last_error_code = None
        db.commit()
        return existing

    delivery = EmailDelivery(
        idempotency_key=idempotency_key,
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
    if idempotency_key is None:
        return delivery
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return None
    return delivery


def _delivery_for_key(db: Session, key: str | None) -> EmailDelivery | None:
    if key is None:
        return None
    return db.scalar(select(EmailDelivery).where(EmailDelivery.idempotency_key == key))
