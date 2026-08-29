"""Rebuild and retry queued email intents without storing rendered credentials."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import (
    EmailDelivery,
    EmailDeliveryState,
    MagicLinkPurpose,
    MagicLinkToken,
    Opening,
    PasswordlessIdentityKind,
    VacancySubscription,
)
from app.services.auth_email import (
    application_confirmation_email,
    application_opening_email,
    application_unavailable_email,
    email_change_notice_email,
    magic_link_email,
    unsuccessful_application_email,
    vacancy_opening_email,
)
from app.services.email_delivery import attempt_reserved_delivery
from app.services.email_sender import EmailSender, OutboundEmail
from app.services.passwordless_auth import issue_magic_link
from app.services.vacancy_notifications import (
    application_confirmation_timelines,
    opening_email_details,
)
from app.services.vacancy_subscriptions import consume_subscription


@dataclass(frozen=True)
class RetrySummary:
    accepted: int = 0
    still_queued: int = 0
    quota_blocked: int = 0


@dataclass(frozen=True)
class EmailQueueStatus:
    count: int = 0
    quota_blocked: int = 0
    recent_failed: int = 0
    oldest_queued_at: datetime | None = None
    newest_queued_at: datetime | None = None
    last_attempt_at: datetime | None = None


def retry_queued_emails(
    db: Session, sender: EmailSender, *, now: datetime | None = None
) -> RetrySummary:
    """Retry every provider-temporary failure once during the daily maintenance pass."""
    now = now or datetime.now(UTC)
    accepted = 0
    queued = 0
    quota_blocked = 0
    deliveries = db.scalars(
        select(EmailDelivery)
        .where(
            EmailDelivery.state == EmailDeliveryState.QUEUED,
            EmailDelivery.retry_intent.is_not(None),
        )
        .order_by(EmailDelivery.id)
    ).all()
    for delivery in deliveries:
        subscription_id = (delivery.retry_intent or {}).get("subscription_id")
        built = _build_retry(db, delivery, now=now)
        if built is None:
            delivery.state = EmailDeliveryState.FAILED
            delivery.retry_intent = None
            delivery.quota_blocked = False
            delivery.last_error_code = "RetryTargetUnavailable"
            db.commit()
            continue
        message, magic_link_token = built
        was_accepted = attempt_reserved_delivery(
            db,
            sender,
            delivery,
            message,
            magic_link_token=magic_link_token,
            now=now,
            is_retry=True,
            commit=False,
        )
        if was_accepted:
            accepted += 1
            if subscription_id is not None:
                consume_subscription(
                    db,
                    int(subscription_id),
                    email_delivery_id=delivery.id,
                    fulfilled_at=now,
                )
        else:
            if delivery.state == EmailDeliveryState.QUEUED:
                queued += 1
            if delivery.quota_blocked:
                quota_blocked += 1
        db.commit()
    return RetrySummary(
        accepted=accepted,
        still_queued=queued,
        quota_blocked=quota_blocked,
    )


EXPECTED_FAILURE_CODES = frozenset({"ApplicationWithdrawn", "Superseded"})
FAILURE_BANNER_WINDOW = timedelta(days=7)


@dataclass(frozen=True)
class EmailDeliveryIssue:
    id: int
    recipient_email: str
    message_kind: str
    state: EmailDeliveryState
    attempted_at: datetime
    attempt_count: int
    error_code: str | None
    quota_blocked: bool


def email_queue_status(
    db: Session, *, now: datetime | None = None
) -> EmailQueueStatus:
    now = now or datetime.now(UTC)
    deliveries = db.scalars(
        select(EmailDelivery).where(
            EmailDelivery.state == EmailDeliveryState.QUEUED,
            EmailDelivery.retry_intent.is_not(None),
        )
    ).all()
    recent_failed = db.scalar(
        select(func.count())
        .select_from(EmailDelivery)
        .where(
            _unexpected_failure_filter(),
            func.coalesce(EmailDelivery.last_attempt_at, EmailDelivery.created_at)
            >= now - FAILURE_BANNER_WINDOW,
        )
    ) or 0
    if not deliveries:
        return EmailQueueStatus(recent_failed=recent_failed)
    return EmailQueueStatus(
        count=len(deliveries),
        quota_blocked=sum(delivery.quota_blocked for delivery in deliveries),
        recent_failed=recent_failed,
        oldest_queued_at=min(delivery.created_at for delivery in deliveries),
        newest_queued_at=max(delivery.created_at for delivery in deliveries),
        last_attempt_at=max(
            (
                delivery.last_attempt_at
                for delivery in deliveries
                if delivery.last_attempt_at is not None
            ),
            default=None,
        ),
    )


def email_delivery_issues(db: Session, *, limit: int = 100) -> list[EmailDeliveryIssue]:
    deliveries = db.scalars(
        select(EmailDelivery)
        .where(
            or_(
                EmailDelivery.state == EmailDeliveryState.QUEUED,
                _unexpected_failure_filter(),
            )
        )
        .order_by(
            func.coalesce(EmailDelivery.last_attempt_at, EmailDelivery.created_at).desc(),
            EmailDelivery.id.desc(),
        )
        .limit(limit)
    ).all()
    return [
        EmailDeliveryIssue(
            id=delivery.id,
            recipient_email=_delivery_recipient(delivery),
            message_kind=delivery.message_kind,
            state=delivery.state,
            attempted_at=delivery.last_attempt_at or delivery.created_at,
            attempt_count=delivery.attempt_count,
            error_code=delivery.last_error_code,
            quota_blocked=delivery.quota_blocked,
        )
        for delivery in deliveries
    ]


def _unexpected_failure_filter():
    return (
        (EmailDelivery.state == EmailDeliveryState.FAILED)
        & or_(
            EmailDelivery.last_error_code.is_(None),
            EmailDelivery.last_error_code.not_in(EXPECTED_FAILURE_CODES),
        )
    )


def _delivery_recipient(delivery: EmailDelivery) -> str:
    if delivery.recipient_email:
        return delivery.recipient_email
    if delivery.application is not None:
        return delivery.application.primary_email
    if delivery.applicant_draft is not None:
        return delivery.applicant_draft.email
    if delivery.user is not None:
        return delivery.user.email
    return "Unavailable"


def _build_retry(
    db: Session, delivery: EmailDelivery, *, now: datetime
) -> tuple[OutboundEmail, MagicLinkToken | None] | None:
    intent = delivery.retry_intent or {}
    intent_type = intent.get("type")
    if intent_type == "magic_link":
        return _build_magic_link_retry(db, delivery, intent, now=now)
    if intent_type == "vacancy_opening":
        opening = db.get(Opening, int(intent["opening_id"]))
        subscription_id = int(intent["subscription_id"])
        if (
            opening is None
            or delivery.recipient_email is None
            or db.get(VacancySubscription, subscription_id) is None
        ):
            return None
        return (
            vacancy_opening_email(
                email=delivery.recipient_email,
                **opening_email_details(opening),
            ),
            None,
        )
    if intent_type == "application_unavailable" and delivery.application is None:
        if delivery.recipient_email is None:
            return None
        return (
            application_unavailable_email(email=delivery.recipient_email),
            None,
        )
    application = delivery.application
    if application is None:
        return None
    if intent_type == "application_confirmation":
        submitted = bool(intent.get("submitted"))
        issued = issue_magic_link(
            db,
            identity_kind=PasswordlessIdentityKind.APPLICANT,
            email=application.primary_email,
            purpose=MagicLinkPurpose.APPLICANT_ACCESS,
            application_id=application.id,
            now=now,
        )
        delivery.magic_link_token_id = issued.record.id
        return (
            application_confirmation_email(
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
            ),
            issued.record,
        )
    if intent_type == "email_change_notice":
        return (
            email_change_notice_email(
                application_id=application.id,
                old_email=str(intent["old_email"]),
                new_email=application.primary_email,
            ),
            None,
        )
    if intent_type == "application_unavailable":
        return (
            application_unavailable_email(
                application_id=application.id,
                email=application.primary_email,
            ),
            None,
        )
    if intent_type == "application_unsuccessful":
        return (
            unsuccessful_application_email(
                application_id=application.id,
                email=application.primary_email,
                opening_labels=[str(label) for label in intent.get("opening_labels", [])],
            ),
            None,
        )
    if intent_type == "application_opening":
        opening = db.get(Opening, int(intent["opening_id"]))
        if opening is None:
            return None
        issued = issue_magic_link(
            db,
            identity_kind=PasswordlessIdentityKind.APPLICANT,
            email=application.primary_email,
            purpose=MagicLinkPurpose.APPLICANT_ACCESS,
            application_id=application.id,
            now=now,
        )
        delivery.magic_link_token_id = issued.record.id
        subscription_id = intent.get("subscription_id")
        overlap = (
            subscription_id is not None
            and db.get(VacancySubscription, int(subscription_id)) is not None
        )
        return (
            application_opening_email(
                application_id=application.id,
                email=application.primary_email,
                token=issued.token,
                notification_list_overlap=overlap,
                settings=get_settings(),
                **opening_email_details(opening),
            ),
            issued.record,
        )
    return None


def _build_magic_link_retry(
    db: Session,
    delivery: EmailDelivery,
    intent: dict[str, object],
    *,
    now: datetime,
) -> tuple[OutboundEmail, MagicLinkToken] | None:
    identity_kind = delivery.recipient_kind
    purpose = MagicLinkPurpose(str(intent["purpose"]))
    if identity_kind == PasswordlessIdentityKind.APPLICANT:
        recipient = delivery.application or delivery.applicant_draft
        if recipient is None:
            return None
        email = (
            recipient.primary_email
            if delivery.application is not None
            else recipient.email
        )
    else:
        recipient = delivery.user
        if recipient is None or not recipient.is_active:
            return None
        email = recipient.email
    issued = issue_magic_link(
        db,
        identity_kind=identity_kind,
        email=email,
        purpose=purpose,
        application_id=delivery.application_id,
        applicant_draft_id=delivery.applicant_draft_id,
        user_id=delivery.user_id,
        now=now,
        remember_device=bool(intent.get("remember_device")),
        initiating_session_id=(
            int(intent["initiating_session_id"])
            if intent.get("initiating_session_id") is not None
            else None
        ),
    )
    delivery.magic_link_token_id = issued.record.id
    return (
        magic_link_email(
            identity_kind=identity_kind,
            purpose=purpose,
            recipient_id=recipient.id,
            email=email,
            token=issued.token,
            settings=get_settings(),
        ),
        issued.record,
    )
