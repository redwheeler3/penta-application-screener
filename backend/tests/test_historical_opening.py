from datetime import UTC, date, datetime

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.db.models import (
    Application,
    ApplicationParticipation,
    Base,
    EmailDelivery,
    EmailDeliveryState,
    Opening,
    PasswordlessIdentityKind,
    VacancyConsentReceipt,
    VacancySubscription,
)
from app.services.historical_opening import (
    HistoricalOpeningDetails,
    create_historical_opening,
    inspect_historical_opening,
)
from app.services.retention import one_year_after

NOW = datetime(2026, 8, 29, 18, tzinfo=UTC)
DETAILS = HistoricalOpeningDetails(
    unit_size_bedrooms=2,
    housing_charge_cents=128_500,
    application_open_date=date(2026, 7, 1),
    application_close_date=date(2026, 8, 1),
    move_in_date=date(2026, 10, 1),
)


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _application(
    db: Session,
    email: str,
    *,
    submitted_at: datetime | None,
    withdrawn_at: datetime | None = None,
) -> Application:
    application = Application(
        primary_email=email,
        raw_row={},
        raw_row_hash=email,
        normalized={},
        submitted_at=submitted_at,
        withdrawn_at=withdrawn_at,
    )
    db.add(application)
    db.flush()
    return application


def test_preflight_reports_reconciliation_counts_without_writing() -> None:
    db = _session()
    submitted = _application(db, "submitted@example.com", submitted_at=NOW)
    _application(db, "draft@example.com", submitted_at=None)
    _application(db, "withdrawn@example.com", submitted_at=NOW, withdrawn_at=NOW)
    prior = Opening(
        unit_size_bedrooms=1,
        housing_charge_cents=100_000,
        application_open_date=date(2025, 1, 1),
        application_close_date=date(2025, 2, 1),
        move_in_date=date(2025, 3, 1),
        published_at=NOW,
    )
    db.add(prior)
    db.flush()
    db.add(ApplicationParticipation(application_id=submitted.id, opening_id=prior.id, applied_at=NOW))
    db.add(
        VacancySubscription(
            email="notice@example.com",
            wants_one_bedroom=True,
            wants_two_bedroom=False,
            wants_three_bedroom=False,
            consented_at=NOW,
            source="test",
        )
    )
    db.add(
        VacancyConsentReceipt(
            subscription_id=1,
            email_hash="hash",
            unit_sizes=[1],
            consented_at=NOW,
            source="test",
            fulfilled_at=NOW,
            retain_until=date(2027, 8, 29),
            email_delivery_id=1,
        )
    )
    db.add(
        EmailDelivery(
            message_kind="test",
            recipient_kind=PasswordlessIdentityKind.APPLICANT,
            recipient_email="notice@example.com",
            state=EmailDeliveryState.QUEUED,
        )
    )
    db.commit()

    report = inspect_historical_opening(db, DETAILS, today=date(2026, 8, 29))

    assert report.target_application_count == 1
    assert report.existing_target_participation_count == 1
    assert report.active_vacancy_subscription_count == 1
    assert report.consent_receipt_count == 1
    assert report.queued_email_count == 1
    assert report.matching_opening_count == 0
    assert db.scalar(select(func.count()).select_from(Opening)) == 1


def test_apply_creates_closed_opening_and_preserves_notification_state() -> None:
    db = _session()
    first_time = datetime(2026, 7, 15, 17, tzinfo=UTC)
    second_time = datetime(2026, 7, 20, 19, tzinfo=UTC)
    first = _application(db, "first@example.com", submitted_at=first_time)
    second = _application(db, "second@example.com", submitted_at=second_time)
    db.commit()

    before = inspect_historical_opening(db, DETAILS, today=date(2026, 8, 29))
    opening, after = create_historical_opening(
        db, DETAILS, expected_application_count=2, now=NOW
    )
    db.commit()

    participations = list(
        db.scalars(
            select(ApplicationParticipation).order_by(ApplicationParticipation.application_id)
        )
    )
    assert opening.application_close_date < date(2026, 8, 29) < opening.move_in_date
    assert [item.application_id for item in participations] == [first.id, second.id]
    assert [item.applied_at.replace(tzinfo=UTC) for item in participations] == [
        first_time,
        second_time,
    ]
    assert first.retention_due_on == one_year_after(DETAILS.move_in_date)
    assert second.retention_due_on == one_year_after(DETAILS.move_in_date)
    assert after.existing_target_participation_count == 2
    assert after.active_vacancy_subscription_count == before.active_vacancy_subscription_count
    assert after.consent_receipt_count == before.consent_receipt_count
    assert after.queued_email_count == before.queued_email_count


@pytest.mark.parametrize("expected_count", [1, 3])
def test_apply_refuses_an_unreconciled_target_count(expected_count: int) -> None:
    db = _session()
    _application(db, "first@example.com", submitted_at=NOW)
    _application(db, "second@example.com", submitted_at=NOW)
    db.commit()

    with pytest.raises(RuntimeError, match="expected"):
        create_historical_opening(
            db, DETAILS, expected_application_count=expected_count, now=NOW
        )

    assert db.scalar(select(func.count()).select_from(Opening)) == 0


def test_apply_refuses_any_existing_target_participation() -> None:
    db = _session()
    application = _application(db, "first@example.com", submitted_at=NOW)
    prior = Opening(
        unit_size_bedrooms=1,
        housing_charge_cents=100_000,
        application_open_date=date(2025, 1, 1),
        application_close_date=date(2025, 2, 1),
        move_in_date=date(2025, 3, 1),
        published_at=NOW,
    )
    db.add(prior)
    db.flush()
    db.add(ApplicationParticipation(application_id=application.id, opening_id=prior.id, applied_at=NOW))
    db.commit()

    with pytest.raises(RuntimeError, match="participation"):
        create_historical_opening(db, DETAILS, expected_application_count=1, now=NOW)

    assert db.scalar(select(func.count()).select_from(Opening)) == 1


def test_apply_refuses_a_duplicate_opening_even_when_it_has_no_participations() -> None:
    db = _session()
    _application(db, "first@example.com", submitted_at=NOW)
    db.add(
        Opening(
            unit_size_bedrooms=DETAILS.unit_size_bedrooms,
            housing_charge_cents=DETAILS.housing_charge_cents,
            application_open_date=DETAILS.application_open_date,
            application_close_date=DETAILS.application_close_date,
            move_in_date=DETAILS.move_in_date,
            published_at=NOW,
        )
    )
    db.commit()

    with pytest.raises(RuntimeError, match="already exists"):
        create_historical_opening(db, DETAILS, expected_application_count=1, now=NOW)

    assert db.scalar(select(func.count()).select_from(Opening)) == 1


@pytest.mark.parametrize(
    ("details", "message"),
    [
        (
            HistoricalOpeningDetails(2, 100_000, date(2026, 8, 2), date(2026, 8, 1), date(2026, 10, 1)),
            "open date",
        ),
        (
            HistoricalOpeningDetails(2, 100_000, date(2026, 7, 1), date(2026, 8, 29), date(2026, 10, 1)),
            "close date",
        ),
        (
            HistoricalOpeningDetails(2, 100_000, date(2026, 7, 1), date(2026, 8, 1), date(2026, 8, 29)),
            "move-in date",
        ),
    ],
)
def test_preflight_requires_an_already_closed_not_archived_opening(
    details: HistoricalOpeningDetails, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        inspect_historical_opening(_session(), details, today=date(2026, 8, 29))
