"""Build and queue the complete audience when an opening is created."""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import exists, not_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.text import normalize_email
from app.db.models import (
    Application,
    ApplicationParticipation,
    MagicLinkPurpose,
    Opening,
    OpeningOutcome,
    PasswordlessIdentityKind,
    VacancySubscription,
)
from app.services.auth_email import application_opening_email, vacancy_opening_email
from app.services.email_delivery import queue_email
from app.services.passwordless_auth import issue_magic_link
from app.services.vacancy_subscriptions import matching_subscriptions


@dataclass(frozen=True)
class VacancyAudience:
    subscriber_only: tuple[VacancySubscription, ...]
    application_only: tuple[Application, ...]
    overlaps: tuple[tuple[Application, VacancySubscription], ...]

    @property
    def total(self) -> int:
        return len(self.subscriber_only) + len(self.application_only) + len(self.overlaps)


def opening_audience(db: Session, unit_size: int) -> VacancyAudience:
    subscriptions = {
        subscription.email: subscription
        for subscription in matching_subscriptions(db, unit_size)
    }
    applications = {
        normalize_email(application.primary_email): application
        for application in _notifiable_applications(db)
    }
    overlap_emails = subscriptions.keys() & applications.keys()
    return VacancyAudience(
        subscriber_only=tuple(
            subscriptions[email] for email in sorted(subscriptions.keys() - overlap_emails)
        ),
        application_only=tuple(
            applications[email] for email in sorted(applications.keys() - overlap_emails)
        ),
        overlaps=tuple(
            (applications[email], subscriptions[email]) for email in sorted(overlap_emails)
        ),
    )


def queue_opening_notifications(
    db: Session,
    opening: Opening,
    audience: VacancyAudience,
    *,
    now: datetime | None = None,
) -> None:
    now = now or datetime.now(UTC)
    details = opening_email_details(opening)
    for subscription in audience.subscriber_only:
        message = vacancy_opening_email(email=subscription.email, **details)
        queue_email(
            db,
            message,
            recipient_kind=PasswordlessIdentityKind.APPLICANT,
            idempotency_key=f"opening:{opening.id}:subscription:{subscription.id}",
            retry_intent={
                "type": "vacancy_opening",
                "opening_id": opening.id,
                "subscription_id": subscription.id,
            },
        )
    for application in audience.application_only:
        _queue_application_notice(db, opening, application, None, details=details, now=now)
    for application, subscription in audience.overlaps:
        _queue_application_notice(
            db,
            opening,
            application,
            subscription,
            details=details,
            now=now,
        )


def _queue_application_notice(
    db: Session,
    opening: Opening,
    application: Application,
    subscription: VacancySubscription | None,
    *,
    details: dict[str, str],
    now: datetime,
) -> None:
    issued = issue_magic_link(
        db,
        identity_kind=PasswordlessIdentityKind.APPLICANT,
        email=application.primary_email,
        purpose=MagicLinkPurpose.APPLICANT_ACCESS,
        application_id=application.id,
        now=now,
    )
    message = application_opening_email(
        application_id=application.id,
        email=application.primary_email,
        token=issued.token,
        notification_list_overlap=subscription is not None,
        settings=get_settings(),
        **details,
    )
    intent: dict[str, object] = {
        "type": "application_opening",
        "opening_id": opening.id,
    }
    if subscription is not None:
        intent["subscription_id"] = subscription.id
    queue_email(
        db,
        message,
        recipient_kind=PasswordlessIdentityKind.APPLICANT,
        application_id=application.id,
        magic_link_token=issued.record,
        idempotency_key=f"opening:{opening.id}:application:{application.id}",
        retry_intent=intent,
    )


def _notifiable_applications(db: Session) -> list[Application]:
    selected = exists(
        select(ApplicationParticipation.id).where(
            ApplicationParticipation.application_id == Application.id,
            ApplicationParticipation.outcome == OpeningOutcome.SELECTED,
        )
    )
    return list(
        db.scalars(
            select(Application)
            .where(
                Application.submitted_at.is_not(None),
                Application.deleted_at.is_(None),
                not_(selected),
            )
            .order_by(Application.id)
        )
    )


def opening_email_details(opening: Opening) -> dict[str, str]:
    unit = f"{opening.unit_size_bedrooms}-bedroom"
    housing_charge = (opening.housing_charge_cents / 100).is_integer()
    charge = f"${opening.housing_charge_cents / 100:,.0f}" if housing_charge else f"${opening.housing_charge_cents / 100:,.2f}"
    household = {
        1: "One or two adults",
        2: "One or two adults and at least one child under 18",
        3: "One or two adults and at least two children under 18",
    }[opening.unit_size_bedrooms]
    return {
        "unit_size": unit,
        "housing_charge": f"{charge} per month",
        "move_in_date": _display_date(opening.move_in_date),
        "close_date": _display_date(opening.application_close_date),
        "household_summary": household,
    }


def _display_date(value) -> str:
    return f"{value.strftime('%B')} {value.day}, {value.year}"
