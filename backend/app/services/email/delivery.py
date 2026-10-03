"""Persist provider-neutral delivery attempts and credential-safe retry intents."""

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import or_, select, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import (
    ApplicantDraft,
    EmailDelivery,
    EmailDeliveryState,
    MagicLinkToken,
    PasswordlessIdentityKind,
)
from app.services.email.retry_intents import RetryIntent
from app.services.email.sender import (
    EmailQuotaExceededError,
    EmailRetryableError,
    EmailSender,
    OutboundEmail,
)

ATTEMPT_LEASE = timedelta(minutes=10)


@dataclass(frozen=True)
class DeliveryAttempt:
    delivery_id: int
    attempt_count: int
    attempted_at: datetime
    retry_intent: RetryIntent | None
    recipient_email: str | None
    token_id: int | None

    @classmethod
    def capture(cls, delivery: EmailDelivery) -> "DeliveryAttempt":
        return cls(
            delivery_id=delivery.id,
            attempt_count=delivery.attempt_count,
            attempted_at=delivery.last_attempt_at,
            retry_intent=delivery.retry_intent,
            recipient_email=delivery.recipient_email,
            token_id=delivery.magic_link_token_id,
        )


def claim_delivery_attempt(
    db: Session, delivery_id: int, *, now: datetime, allow_failed: bool = False,
    commit: bool = True,
) -> DeliveryAttempt | None:
    """Reserve one provider attempt before rebuilding credentials or contacting the provider.

    The existing attempt timestamp is the lease; its counter identifies successive
    attempts. A provider failure releases the lease through its error code; a crashed
    worker with no outcome becomes retryable when the lease expires.
    """
    available = (
        (EmailDelivery.state == EmailDeliveryState.QUEUED)
        & or_(
            EmailDelivery.last_error_code.is_not(None),
            EmailDelivery.last_attempt_at.is_(None),
            EmailDelivery.last_attempt_at <= now - ATTEMPT_LEASE,
        )
    )
    if allow_failed:
        available = available | (EmailDelivery.state == EmailDeliveryState.FAILED)
    statement = (
        update(EmailDelivery)
        .where(EmailDelivery.id == delivery_id, available)
        .values(
            state=EmailDeliveryState.QUEUED,
            attempt_count=EmailDelivery.attempt_count + 1,
            last_attempt_at=now,
            last_error_code=None,
        )
        .returning(EmailDelivery)
        .execution_options(synchronize_session=False)
    )
    delivery = db.scalars(statement, execution_options={"populate_existing": True}).one_or_none()
    attempt = DeliveryAttempt.capture(delivery) if delivery is not None else None
    if commit:
        db.commit()
    return attempt


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
    retry_intent: RetryIntent | None = None,
    now: datetime | None = None,
) -> bool:
    """Attempt one send and durably record its provider outcome."""
    now = now or datetime.now(UTC)
    attempt = _reserve_delivery(
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
    if attempt is None:
        existing = _delivery_for_key(db, idempotency_key)
        return existing is not None and existing.state == EmailDeliveryState.ACCEPTED
    return attempt_reserved_delivery(
        db,
        sender,
        attempt,
        message,
        now=now,
    )


def queue_email(
    db: Session,
    message: OutboundEmail,
    *,
    recipient_kind: PasswordlessIdentityKind,
    application_id: int | None = None,
    user_id: int | None = None,
    magic_link_token: MagicLinkToken | None = None,
    idempotency_key: str,
    retry_intent: RetryIntent,
) -> EmailDelivery:
    """Add an outbox intent to the caller's transaction without contacting the provider."""
    statement = insert(EmailDelivery).values(
        idempotency_key=idempotency_key,
        message_kind=message.kind,
        recipient_kind=recipient_kind,
        application_id=application_id,
        user_id=user_id,
        magic_link_token_id=magic_link_token.id if magic_link_token is not None else None,
        recipient_email=message.to[0] if application_id is None and user_id is None else None,
        state=EmailDeliveryState.QUEUED,
        retry_intent=retry_intent,
        quota_blocked=False,
        attempt_count=0,
    ).on_conflict_do_nothing(index_elements=[EmailDelivery.idempotency_key]).returning(EmailDelivery)
    delivery = db.scalars(statement, execution_options={"populate_existing": True}).one_or_none()
    if delivery is not None:
        return delivery
    return db.scalar(select(EmailDelivery).where(EmailDelivery.idempotency_key == idempotency_key)
        .execution_options(populate_existing=True))


def attempt_reserved_delivery(
    db: Session,
    sender: EmailSender,
    attempt: DeliveryAttempt,
    message: OutboundEmail,
    *,
    now: datetime | None = None,
    commit: bool = True,
) -> bool:
    """Attempt a reserved intent without ever persisting rendered credential content."""
    now = now or datetime.now(UTC)
    retry_intent = attempt.retry_intent
    recipient_email = attempt.recipient_email
    provider_message_id = None
    error_code = None
    quota_blocked = False
    try:
        provider_message_id = sender.send(message)
        state = EmailDeliveryState.ACCEPTED
        retry_intent = None
        recipient_email = None
    except EmailQuotaExceededError as error:
        state = EmailDeliveryState.QUEUED
        quota_blocked = True
        error_code = type(error).__name__[:120]
    except (EmailRetryableError, httpx.TransportError) as error:
        state = EmailDeliveryState.QUEUED
        error_code = type(error).__name__[:120]
    except Exception as error:
        state = EmailDeliveryState.FAILED
        retry_intent = None
        error_code = type(error).__name__[:120]
    # A cancelled intent or a newer attempt owns the row now. A late provider
    # response must not revive it or replace that attempt's delivery outcome.
    finished = db.execute(
        update(EmailDelivery)
        .where(
            EmailDelivery.id == attempt.delivery_id,
            EmailDelivery.state == EmailDeliveryState.QUEUED,
            EmailDelivery.attempt_count == attempt.attempt_count,
            EmailDelivery.last_attempt_at == attempt.attempted_at,
        )
        .values(
            state=state, provider_message_id=provider_message_id,
            last_error_code=error_code, quota_blocked=quota_blocked,
            retry_intent=retry_intent, recipient_email=recipient_email,
        )
        .execution_options(synchronize_session=False)
    )
    if attempt.token_id is not None and (state != EmailDeliveryState.ACCEPTED or finished.rowcount != 1):
        db.execute(update(MagicLinkToken).where(
            MagicLinkToken.id == attempt.token_id, MagicLinkToken.consumed_at.is_(None),
        ).values(revoked_at=now))
    db.expire_all()
    if commit:
        db.commit()
    return finished.rowcount == 1 and state == EmailDeliveryState.ACCEPTED


def cancel_queued_application_emails(
    db: Session,
    application_id: int,
    *,
    error_code: str = "ApplicationWithdrawn",
) -> None:
    """Discard queued intents made obsolete by an applicant lifecycle change."""
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
        delivery.last_error_code = error_code


def cancel_queued_committee_emails(
    db: Session,
    user_id: int,
    *,
    error_code: str = "CommitteeAccessRemoved",
) -> None:
    """Discard committee email intents made obsolete by removing access."""
    deliveries = db.scalars(
        select(EmailDelivery).where(
            EmailDelivery.user_id == user_id,
            EmailDelivery.state == EmailDeliveryState.QUEUED,
        )
    ).all()
    for delivery in deliveries:
        delivery.state = EmailDeliveryState.FAILED
        delivery.retry_intent = None
        delivery.quota_blocked = False
        delivery.last_error_code = error_code


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
    retry_intent: RetryIntent | None,
    now: datetime,
) -> DeliveryAttempt | None:
    existing = _delivery_for_key(db, idempotency_key)
    if existing is not None:
        attempt = claim_delivery_attempt(db, existing.id, now=now, allow_failed=True, commit=False)
        if attempt is None:
            db.commit()
            return None
        existing = db.get(EmailDelivery, attempt.delivery_id)
        existing.retry_intent = retry_intent
        existing.quota_blocked = False
        attempt = replace(attempt, retry_intent=retry_intent,
            token_id=magic_link_token.id if magic_link_token is not None else None)
        db.commit()
        return attempt

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
        db.flush()
        attempt = DeliveryAttempt.capture(delivery)
        db.commit()
    except IntegrityError:
        db.rollback()
        return None
    return attempt


def _delivery_for_key(db: Session, key: str | None) -> EmailDelivery | None:
    if key is None:
        return None
    return db.scalar(select(EmailDelivery).where(EmailDelivery.idempotency_key == key))
