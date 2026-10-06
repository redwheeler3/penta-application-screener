"""Rebuild and retry queued email intents without storing rendered credentials."""

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import cast

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.text import normalize_email
from app.core.time import pacific_today
from app.db.models import (
    EmailDelivery,
    EmailDeliveryState,
    MagicLinkPurpose,
    MagicLinkToken,
    Opening,
    OpeningPhase,
    PasswordlessIdentityKind,
    VacancySubscription,
)
from app.services.applications.drafts import draft_is_available
from app.services.applications.retention import retention_is_current
from app.services.applications.selected import application_is_selected
from app.services.auth.passwordless import issue_magic_link
from app.services.email.delivery import (
    attempt_reserved_delivery,
    claim_delivery_attempt,
)
from app.services.email.retry_intents import MagicLinkRetryIntent, RetryIntent
from app.services.email.sender import EmailSender, OutboundEmail
from app.services.email.templates import (
    application_confirmation_email,
    application_opening_email,
    application_unavailable_email,
    committee_invitation_email,
    email_change_notice_email,
    magic_link_email,
    selected_application_locked_email,
    unsuccessful_application_email,
    vacancy_opening_email,
)
from app.services.openings.catalog import opening_phase
from app.services.openings.notifications import (
    record_unsuccessful_delivery,
    unsuccessful_notice_is_available,
)
from app.services.openings.subscriptions import consume_subscription, unit_sizes
from app.services.openings.vacancy_notifications import (
    application_confirmation_timelines,
    notifiable_application,
    opening_email_details,
)


@dataclass(frozen=True)
class RetrySummary:
    accepted: int = 0
    still_queued: int = 0
    quota_blocked: int = 0


@dataclass(frozen=True)
class PreparedRetry:
    message: OutboundEmail
    magic_link_token: MagicLinkToken | None = None
    subscription_id: int | None = None
    subscription_consented_at: datetime | None = None


@dataclass(frozen=True)
class EmailQueueStatus:
    count: int = 0
    quota_blocked: int = 0
    recent_failed: int = 0
    oldest_queued_at: datetime | None = None
    newest_queued_at: datetime | None = None
    last_attempt_at: datetime | None = None


VACANCY_FAILURE_RETENTION = timedelta(days=30)


def retry_queued_emails(
    db: Session, sender: EmailSender, *, now: datetime | None = None
) -> RetrySummary:
    """Retry every provider-temporary failure once during the daily maintenance pass."""
    accepted = 0
    queued = 0
    quota_blocked = 0
    delivery_ids = db.scalars(
        select(EmailDelivery.id)
        .where(
            EmailDelivery.state == EmailDeliveryState.QUEUED,
            EmailDelivery.retry_intent.is_not(None),
        )
        .order_by(EmailDelivery.id)
    ).all()
    for delivery_id in delivery_ids:
        attempt_time = now or datetime.now(UTC)
        attempt = claim_delivery_attempt(db, delivery_id, now=attempt_time, commit=False)
        if attempt is None:
            db.commit()
            continue
        delivery = db.get(EmailDelivery, delivery_id)
        try:
            # Roll back partial credentials if one intent cannot be prepared, while
            # retaining its claimed attempt and allowing the rest of the batch to run.
            with db.begin_nested():
                built = _build_retry(db, delivery, now=attempt_time)
        except Exception as error:
            delivery.last_error_code = f"Preparation:{type(error).__name__}"[:120]
            built = None
        if built is None:
            vacancy_request = (delivery.retry_intent or {}).get("type") == "vacancy_opening"
            delivery.state = EmailDeliveryState.FAILED
            delivery.retry_intent = None
            delivery.quota_blocked = False
            delivery.last_error_code = delivery.last_error_code or ("VacancyRequestUnavailable" if vacancy_request else "RetryTargetUnavailable")
            db.commit()
            continue
        # Publish the fresh credential before network I/O; a recipient can use it
        # immediately, and the provider wait does not hold SQLite's writer lock.
        attempt = replace(attempt,
            token_id=built.magic_link_token.id if built.magic_link_token is not None else None)
        db.commit()
        was_accepted = attempt_reserved_delivery(
            db,
            sender,
            attempt,
            built.message,
            now=attempt_time,
            commit=False,
        )
        delivery = db.get(EmailDelivery, delivery_id, populate_existing=True)
        if delivery is None:
            db.commit()
            continue
        if was_accepted:
            accepted += 1
            if delivery.message_kind == "application_unsuccessful":
                record_unsuccessful_delivery(db, delivery)
            if built.subscription_id is not None and built.subscription_consented_at is not None:
                consume_subscription(
                    db,
                    built.subscription_id,
                    consented_at=built.subscription_consented_at,
                )
                if delivery.application_id is None:
                    db.delete(delivery)
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


def purge_expired_vacancy_delivery_failures(
    db: Session, *, now: datetime | None = None
) -> int:
    """Delete terminal list-only vacancy failures after the troubleshooting window."""
    now = now or datetime.now(UTC)
    result = db.execute(
        delete(EmailDelivery).where(
            EmailDelivery.message_kind == "vacancy_opening",
            EmailDelivery.application_id.is_(None),
            EmailDelivery.state == EmailDeliveryState.FAILED,
            func.coalesce(EmailDelivery.last_attempt_at, EmailDelivery.created_at)
            <= now - VACANCY_FAILURE_RETENTION,
        )
    )
    db.commit()
    return int(result.rowcount or 0)


EXPECTED_FAILURE_CODES = frozenset(
    {
        "ApplicationSelected",
        "ApplicationWithdrawn",
        "CommitteeAccessRemoved",
        "CredentialUsed",
        "RecoveryReset",
        "VacancyRequestUnavailable",
        "OutcomeNoLongerDue",
        "EmailChangeCancelled",
        "OpeningNoLongerOpen",
        "ApplicationNoLongerNotifiable",
        "SubmissionNoLongerDue",
        "ApplicantDraftUnavailable",
    }
)
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
) -> PreparedRetry | None:
    if delivery.retry_intent is None:
        return None
    # The ledger stores JSON; every producer constructs a named RetryIntent.
    intent = cast(RetryIntent, delivery.retry_intent)
    if intent["type"] == "magic_link":
        return _build_magic_link_retry(db, delivery, intent, now=now)
    if intent["type"] == "vacancy_opening":
        opening = _opening_for_notice(db, delivery, int(intent["opening_id"]), now=now)
        if opening is None:
            return None
        subscription_id = int(intent["subscription_id"])
        subscription = db.get(VacancySubscription, subscription_id, populate_existing=True)
        if (
            delivery.recipient_email is None
            or subscription is None
            or subscription.email != normalize_email(delivery.recipient_email)
            or opening.unit_size_bedrooms not in unit_sizes(subscription)
        ):
            return None
        return PreparedRetry(
            vacancy_opening_email(
                email=delivery.recipient_email,
                **opening_email_details(opening),
            ),
            subscription_id=subscription.id,
            subscription_consented_at=subscription.consented_at,
        )
    if intent["type"] == "application_unavailable" and delivery.application is None:
        if delivery.recipient_email is None:
            return None
        return PreparedRetry(
            application_unavailable_email(email=delivery.recipient_email),
            None,
        )
    application = delivery.application
    if application is None:
        return None
    if not retention_is_current(application, now=now):
        delivery.last_error_code = ("ApplicationNoLongerNotifiable"
                                    if intent["type"] == "application_opening" else "ApplicationExpired")
        return None
    if intent["type"] == "application_confirmation":
        submitted = bool(intent.get("submitted"))
        timelines = application_confirmation_timelines(db, application.id) if submitted else []
        if submitted and not timelines:
            delivery.last_error_code = "SubmissionNoLongerDue"
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
        return PreparedRetry(
            application_confirmation_email(
                application_id=application.id,
                email=application.primary_email,
                token=issued.token,
                submitted=submitted,
                opening_timelines=timelines,
                settings=get_settings(),
            ),
            issued.record,
        )
    if intent["type"] == "email_change_notice":
        return PreparedRetry(
            email_change_notice_email(
                application_id=application.id,
                old_email=str(intent["old_email"]),
                new_email=application.primary_email,
            ),
            None,
        )
    if intent["type"] == "application_unavailable":
        return PreparedRetry(
            application_unavailable_email(
                application_id=application.id,
                email=application.primary_email,
            ),
            None,
        )
    if intent["type"] == "application_selected_locked":
        if not application_is_selected(db, application.id):
            return None
        return PreparedRetry(
            selected_application_locked_email(
                application_id=application.id,
                email=application.primary_email,
            ),
            None,
        )
    if intent["type"] == "application_unsuccessful":
        if not unsuccessful_notice_is_available(db, application, now=now):
            delivery.last_error_code = "OutcomeNoLongerDue"
            return None
        return PreparedRetry(
            unsuccessful_application_email(
                application_id=application.id,
                email=application.primary_email,
                opening_labels=[str(label) for label in intent.get("opening_labels", [])],
            ),
            None,
        )
    if intent["type"] == "application_opening":
        opening = _opening_for_notice(db, delivery, int(intent["opening_id"]), now=now)
        if opening is None:
            return None
        application = notifiable_application(db, application.id, today=pacific_today(now=now))
        if application is None:
            delivery.last_error_code = "ApplicationNoLongerNotifiable"
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
        subscription = (
            db.get(VacancySubscription, int(subscription_id), populate_existing=True)
            if subscription_id is not None else None
        )
        overlap = (
            subscription is not None
            and subscription.email == normalize_email(application.primary_email)
            and opening.unit_size_bedrooms in unit_sizes(subscription)
        )
        return PreparedRetry(
            application_opening_email(
                application_id=application.id,
                email=application.primary_email,
                token=issued.token,
                notification_list_overlap=overlap,
                settings=get_settings(),
                **opening_email_details(opening),
            ),
            issued.record,
            subscription_id=subscription.id if overlap else None,
            subscription_consented_at=subscription.consented_at if overlap else None,
        )
    return None


def _opening_for_notice(db: Session, delivery: EmailDelivery, opening_id: int, *, now: datetime) -> Opening | None:
    opening = db.get(Opening, opening_id, populate_existing=True)
    if (
        opening is None
        or opening.published_at is None
        or opening_phase(opening, today=pacific_today(now=now)) != OpeningPhase.OPEN
    ):
        delivery.last_error_code = "OpeningNoLongerOpen"
        return None
    return opening


def _build_magic_link_retry(
    db: Session,
    delivery: EmailDelivery,
    intent: MagicLinkRetryIntent,
    *,
    now: datetime,
) -> PreparedRetry | None:
    identity_kind = delivery.recipient_kind
    purpose = MagicLinkPurpose(str(intent["purpose"]))
    if identity_kind == PasswordlessIdentityKind.APPLICANT:
        if delivery.applicant_draft is not None and not draft_is_available(delivery.applicant_draft, now=now):
            delivery.last_error_code = "ApplicantDraftUnavailable"
            return None
        recipient = delivery.application or delivery.applicant_draft
        if recipient is None:
            return None
        email = (
            recipient.primary_email
            if delivery.application is not None
            else recipient.email
        )
        if purpose == MagicLinkPurpose.EMAIL_CHANGE:
            requested_link = delivery.magic_link_token
            if requested_link is None or requested_link.purpose != purpose:
                return None
            # Failed attempts revoke the credential, but its target remains the request's address.
            email = requested_link.email
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
    message = (
        committee_invitation_email(
            user_id=recipient.id,
            email=email,
            role=recipient.role,
            token=issued.token,
            settings=get_settings(),
        )
        if intent.get("committee_invitation")
        else magic_link_email(
            identity_kind=identity_kind,
            purpose=purpose,
            recipient_id=recipient.id,
            email=email,
            token=issued.token,
            settings=get_settings(),
        )
    )
    return PreparedRetry(message, issued.record)
