"""Guarded one-time creation of the first historical application opening."""

from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.time import pacific_today
from app.db.models import (
    Application,
    ApplicationParticipation,
    EmailDelivery,
    EmailDeliveryState,
    Opening,
    OpeningIntakeMode,
    VacancyConsentReceipt,
    VacancySubscription,
)
from app.services.retention import refresh_application_retention


@dataclass(frozen=True)
class HistoricalOpeningDetails:
    unit_size_bedrooms: int
    housing_charge_cents: int
    application_open_date: date
    application_close_date: date
    move_in_date: date


@dataclass(frozen=True)
class HistoricalOpeningReport:
    details: HistoricalOpeningDetails
    target_application_count: int
    existing_target_participation_count: int
    active_vacancy_subscription_count: int
    consent_receipt_count: int
    queued_email_count: int
    matching_opening_count: int


def inspect_historical_opening(
    db: Session,
    details: HistoricalOpeningDetails,
    *,
    today: date | None = None,
) -> HistoricalOpeningReport:
    """Return the complete preflight report without changing the database."""
    _validate_details(details, today=today or pacific_today())
    target_filter = (
        Application.submitted_at.is_not(None),
        Application.withdrawn_at.is_(None),
    )
    target_count = _count(db, select(func.count()).select_from(Application).where(*target_filter))
    participation_count = _count(
        db,
        select(func.count())
        .select_from(ApplicationParticipation)
        .join(Application, Application.id == ApplicationParticipation.application_id)
        .where(*target_filter),
    )
    matching_opening_count = _count(
        db,
        select(func.count())
        .select_from(Opening)
        .where(
            Opening.intake_mode == OpeningIntakeMode.APPLICATIONS,
            Opening.unit_size_bedrooms == details.unit_size_bedrooms,
            Opening.housing_charge_cents == details.housing_charge_cents,
            Opening.application_open_date == details.application_open_date,
            Opening.application_close_date == details.application_close_date,
            Opening.move_in_date == details.move_in_date,
        ),
    )
    return HistoricalOpeningReport(
        details=details,
        target_application_count=target_count,
        existing_target_participation_count=participation_count,
        active_vacancy_subscription_count=_count(
            db, select(func.count()).select_from(VacancySubscription)
        ),
        consent_receipt_count=_count(
            db, select(func.count()).select_from(VacancyConsentReceipt)
        ),
        queued_email_count=_count(
            db,
            select(func.count())
            .select_from(EmailDelivery)
            .where(EmailDelivery.state == EmailDeliveryState.QUEUED),
        ),
        matching_opening_count=matching_opening_count,
    )


def create_historical_opening(
    db: Session,
    details: HistoricalOpeningDetails,
    *,
    expected_application_count: int,
    now: datetime | None = None,
) -> tuple[Opening, HistoricalOpeningReport]:
    """Create and attach the historical opening without committing the transaction."""
    now = now or datetime.now(UTC)
    report = inspect_historical_opening(db, details, today=pacific_today(now=now))
    if expected_application_count <= 0:
        raise RuntimeError("Expected application count must be greater than zero.")
    if report.target_application_count != expected_application_count:
        raise RuntimeError(
            "Historical opening blocked: expected "
            f"{expected_application_count} target application(s), found "
            f"{report.target_application_count}."
        )
    if report.existing_target_participation_count:
        raise RuntimeError(
            "Historical opening blocked: "
            f"{report.existing_target_participation_count} target participation(s) already exist."
        )
    if report.matching_opening_count:
        raise RuntimeError("Historical opening blocked: an opening with these details already exists.")

    applications = list(
        db.scalars(
            select(Application)
            .where(
                Application.submitted_at.is_not(None),
                Application.withdrawn_at.is_(None),
            )
            .order_by(Application.id)
        )
    )
    if len(applications) != expected_application_count:
        raise RuntimeError("Historical opening blocked: the target pool changed during preflight.")

    opening = Opening(
        intake_mode=OpeningIntakeMode.APPLICATIONS,
        unit_size_bedrooms=details.unit_size_bedrooms,
        housing_charge_cents=details.housing_charge_cents,
        application_open_date=details.application_open_date,
        application_close_date=details.application_close_date,
        move_in_date=details.move_in_date,
        published_at=now,
    )
    db.add(opening)
    db.flush()
    for application in applications:
        db.add(
            ApplicationParticipation(
                application_id=application.id,
                opening_id=opening.id,
                applied_at=application.submitted_at,
            )
        )
    db.flush()
    for application in applications:
        refresh_application_retention(db, application)
    db.flush()

    after = inspect_historical_opening(db, details, today=pacific_today(now=now))
    unchanged_counts = (
        after.active_vacancy_subscription_count == report.active_vacancy_subscription_count
        and after.consent_receipt_count == report.consent_receipt_count
        and after.queued_email_count == report.queued_email_count
    )
    if after.existing_target_participation_count != expected_application_count:
        raise RuntimeError("Historical opening blocked: not every target application was attached.")
    if after.matching_opening_count != 1:
        raise RuntimeError("Historical opening blocked: opening creation could not be verified.")
    if not unchanged_counts:
        raise RuntimeError("Historical opening blocked: notification state changed unexpectedly.")
    return opening, after


def _validate_details(details: HistoricalOpeningDetails, *, today: date) -> None:
    if details.unit_size_bedrooms not in (1, 2, 3):
        raise ValueError("Unit size must be 1, 2, or 3 bedrooms.")
    if details.housing_charge_cents < 0:
        raise ValueError("Housing charge cannot be negative.")
    if details.application_open_date > details.application_close_date:
        raise ValueError("Application open date must be on or before the close date.")
    if details.application_close_date >= today:
        raise ValueError("Historical opening close date must be before today.")
    if details.move_in_date <= today:
        raise ValueError("Historical opening move-in date must be in the future.")


def _count(db: Session, statement) -> int:
    return db.scalar(statement) or 0
