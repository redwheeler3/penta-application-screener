"""Persist provider-neutral delivery attempts and credential-safe retry intents."""

from datetime import UTC, datetime, timedelta

import httpx
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
from app.services.email_sender import (
    EmailQuotaExceededError,
    EmailRetryableError,
    EmailSender,
    OutboundEmail,
)


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
    retry_intent: dict[str, object] | None = None,
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
        retry_intent=retry_intent,
        now=now,
    )
    if delivery is None:
        existing = _delivery_for_key(db, idempotency_key)
        return existing is not None and existing.state == EmailDeliveryState.ACCEPTED
    return attempt_reserved_delivery(
        db,
        sender,
        delivery,
        message,
        magic_link_token=magic_link_token,
        now=now,
    )


def queue_email(
    db: Session,
    message: OutboundEmail,
    *,
    recipient_kind: PasswordlessIdentityKind,
    application_id: int | None = None,
    magic_link_token: MagicLinkToken | None = None,
    idempotency_key: str,
    retry_intent: dict[str, object],
) -> EmailDelivery:
    """Add an outbox intent to the caller's transaction without contacting the provider."""
    delivery = EmailDelivery(
        idempotency_key=idempotency_key,
        message_kind=message.kind,
        recipient_kind=recipient_kind,
        application_id=application_id,
        magic_link_token_id=magic_link_token.id if magic_link_token is not None else None,
        recipient_email=message.to[0] if application_id is None else None,
        state=EmailDeliveryState.QUEUED,
        retry_intent=retry_intent,
        quota_blocked=False,
        attempt_count=0,
    )
    db.add(delivery)
    db.flush()
    return delivery


def attempt_reserved_delivery(
    db: Session,
    sender: EmailSender,
    delivery: EmailDelivery,
    message: OutboundEmail,
    *,
    magic_link_token: MagicLinkToken | None = None,
    now: datetime | None = None,
    is_retry: bool = False,
    commit: bool = True,
) -> bool:
    """Attempt a reserved intent without ever persisting rendered credential content."""
    now = now or datetime.now(UTC)
    if is_retry:
        delivery.attempt_count += 1
        delivery.last_attempt_at = now
    delivery.provider_message_id = None
    delivery.last_error_code = None
    try:
        delivery.provider_message_id = sender.send(message)
        delivery.state = EmailDeliveryState.ACCEPTED
        delivery.quota_blocked = False
        delivery.retry_intent = None
    except EmailQuotaExceededError as error:
        _queue_retry(delivery, error, quota_blocked=True)
    except (EmailRetryableError, httpx.TransportError) as error:
        _queue_retry(delivery, error, quota_blocked=False)
    except Exception as error:
        delivery.state = EmailDeliveryState.FAILED
        delivery.quota_blocked = False
        delivery.retry_intent = None
        delivery.last_error_code = type(error).__name__[:120]
    if delivery.state != EmailDeliveryState.QUEUED:
        delivery.recipient_email = None
    if delivery.state != EmailDeliveryState.ACCEPTED and magic_link_token is not None:
        magic_link_token.revoked_at = now
    if commit:
        db.commit()
    return delivery.state == EmailDeliveryState.ACCEPTED


def _queue_retry(
    delivery: EmailDelivery, error: Exception, *, quota_blocked: bool
) -> None:
    delivery.state = EmailDeliveryState.QUEUED
    delivery.quota_blocked = quota_blocked
    delivery.last_error_code = type(error).__name__[:120]


def cancel_queued_application_emails(db: Session, application_id: int) -> None:
    """Discard intents made obsolete when an applicant withdraws the application."""
    deliveries = db.scalars(
        select(EmailDelivery).where(
            EmailDelivery.application_id == application_id,
            EmailDelivery.state == EmailDeliveryState.QUEUED,
        )
    ).all()
    for delivery in deliveries:
        delivery.state = EmailDeliveryState.FAILED
        delivery.retry_intent = None
        delivery.quota_blocked = False
        delivery.last_error_code = "ApplicationWithdrawn"
    db.commit()


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
    retry_intent: dict[str, object] | None,
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
        existing.retry_intent = retry_intent
        existing.quota_blocked = False
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
        recipient_email=(
            message.to[0]
            if application_id is None and applicant_draft is None and user_id is None
            else None
        ),
        state=EmailDeliveryState.QUEUED,
        retry_intent=retry_intent,
        quota_blocked=False,
        attempt_count=1,
        last_attempt_at=now,
    )
    db.add(delivery)
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
