from datetime import UTC, date, datetime, timedelta

import pytest
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import require_current_user
from app.api.openings import get_outbox_runner
from app.core.time import pacific_today
from app.db.models import (
    Application,
    ApplicationParticipation,
    Base,
    EmailDelivery,
    EmailDeliveryState,
    Opening,
    OpeningOutcome,
    User,
    UserRole,
    VacancyConsentReceipt,
    VacancySubscription,
)
from app.db.session import get_db
from app.main import create_app
from app.services.email_outbox import retry_queued_emails
from app.services.email_sender import (
    CapturedEmailSender,
    EmailRetryableError,
    get_email_sender,
)
from app.services.retention import one_year_after
from app.services.socketlabs_usage import SocketLabsUsage, get_socketlabs_usage_reader
from app.services.vacancy_notifications import opening_audience
from app.services.vacancy_subscriptions import save_subscription


class FakeUsageReader:
    def fetch(self) -> SocketLabsUsage:
        return SocketLabsUsage(
            retrieved_at=datetime(2026, 8, 27, 18, tzinfo=UTC),
            billing_period_start=datetime(2026, 8, 1, tzinfo=UTC),
            billing_period_end=datetime(2026, 9, 1, tzinfo=UTC),
            messages_used=1_100,
            message_allowance=2_000,
            messages_used_percent=55,
            allow_overages=False,
        )


class RetryableSender:
    def send(self, _message) -> str:
        raise EmailRetryableError("temporary")


def _app_and_db(sender=None) -> tuple:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    db = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    Base.metadata.create_all(engine)
    admin = User(email="admin@example.com", display_name="Admin", role=UserRole.ADMIN, is_active=True)
    db.add(admin)
    db.commit()
    email_sender = sender or CapturedEmailSender()
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_current_user] = lambda: admin
    app.dependency_overrides[get_email_sender] = lambda: email_sender
    app.dependency_overrides[get_socketlabs_usage_reader] = FakeUsageReader
    app.dependency_overrides[get_outbox_runner] = lambda: (
        lambda active_sender: retry_queued_emails(db, active_sender)
    )
    return app, db, email_sender


def _application(email: str, *, selected: bool = False) -> Application:
    application = Application(
        primary_email=email,
        raw_row={},
        raw_row_hash=f"synthetic-{email}",
        normalized={},
        submitted_at=datetime(2026, 8, 1, tzinfo=UTC),
        retention_due_on=date(2027, 8, 1),
    )
    application._selected_for_test = selected
    return application


def _opening_payload(expected: int | None = None) -> dict:
    today = pacific_today()
    payload = {
        "unitSizeBedrooms": 2,
        "housingChargeCents": 122_600,
        "applicationCloseDate": (today + timedelta(days=20)).isoformat(),
        "moveInDate": (today + timedelta(days=45)).isoformat(),
    }
    if expected is not None:
        payload["expectedAudienceCount"] = expected
    return payload


@pytest.mark.anyio
async def test_preview_counts_each_email_variant_and_projects_usage() -> None:
    app, db, _ = _app_and_db()
    app_only = _application("application@example.com")
    overlap = _application("overlap@example.com")
    db.add_all([app_only, overlap])
    db.commit()
    save_subscription(db, email="list@example.com", unit_sizes={2}, source="public website")
    save_subscription(db, email="overlap@example.com", unit_sizes={2, 3}, source="public website")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/openings/preview", json=_opening_payload())

    assert response.status_code == 200
    assert response.json()["audienceCount"] == 3
    assert response.json()["subscriberOnlyCount"] == 1
    assert response.json()["applicationOnlyCount"] == 1
    assert response.json()["overlapCount"] == 1
    assert response.json()["socketlabs"]["messagesUsed"] == 1_100
    assert response.json()["socketlabs"]["projectedMessagesUsed"] == 1_103


def test_archived_application_inside_retention_is_in_the_opening_audience() -> None:
    _app, db, _sender = _app_and_db()
    application = _application("archived@example.com")
    archived = Opening(
        unit_size_bedrooms=2,
        housing_charge_cents=120_000,
        application_open_date=date(2026, 6, 1),
        application_close_date=date(2026, 6, 15),
        move_in_date=date(2026, 7, 1),
        published_at=datetime(2026, 6, 1, tzinfo=UTC),
    )
    db.add_all([application, archived])
    db.flush()
    db.add(
        ApplicationParticipation(
            application_id=application.id,
            opening_id=archived.id,
            applied_at=application.submitted_at,
            outcome=OpeningOutcome.UNSUCCESSFUL,
        )
    )
    db.commit()

    audience = opening_audience(db, 3)

    assert audience.application_only == (application,)


@pytest.mark.anyio
async def test_create_atomically_opens_and_queues_then_delivers_all_variants() -> None:
    app, db, sender = _app_and_db()
    db.add_all([
        _application("application@example.com"),
        _application("overlap@example.com"),
    ])
    db.commit()
    save_subscription(db, email="list@example.com", unit_sizes={2}, source="public website")
    save_subscription(db, email="overlap@example.com", unit_sizes={2, 3}, source="public website")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/openings", json=_opening_payload(expected=3))

    opening = db.scalar(select(Opening))
    deliveries = list(db.scalars(select(EmailDelivery).order_by(EmailDelivery.id)))
    assert response.status_code == 200
    assert response.json()["queuedNotificationCount"] == 3
    assert opening is not None
    assert opening.published_at is not None
    assert opening.application_open_date == pacific_today()
    assert len(deliveries) == 3
    assert all(delivery.state == EmailDeliveryState.ACCEPTED for delivery in deliveries)
    assert {message.kind for message in sender.messages} == {
        "vacancy_opening",
        "application_opening",
        "application_opening_with_vacancy_notice",
    }
    application_messages = [
        message for message in sender.messages if message.kind != "vacancy_opening"
    ]
    assert all(
        "previously submitted a Penta housing application" in message.text_body
        for message in application_messages
    )
    assert all(
        "current Penta housing application" not in message.text_body
        for message in application_messages
    )
    assert db.scalar(select(func.count()).select_from(VacancySubscription)) == 0
    receipts = list(db.scalars(select(VacancyConsentReceipt).order_by(VacancyConsentReceipt.id)))
    assert len(receipts) == 2
    assert {tuple(receipt.unit_sizes) for receipt in receipts} == {(2,), (2, 3)}
    assert all(receipt.email_hash != "" for receipt in receipts)
    assert all(
        receipt.retain_until == one_year_after(receipt.fulfilled_at.date())
        for receipt in receipts
    )


@pytest.mark.anyio
async def test_create_keeps_subscription_and_intent_when_provider_is_temporary() -> None:
    app, db, _ = _app_and_db(RetryableSender())
    save_subscription(db, email="list@example.com", unit_sizes={2}, source="public website")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/openings", json=_opening_payload(expected=1))

    delivery = db.scalar(select(EmailDelivery))
    assert response.status_code == 200
    assert db.scalar(select(Opening)) is not None
    assert db.scalar(select(VacancySubscription)) is not None
    assert delivery is not None
    assert delivery.state == EmailDeliveryState.QUEUED


@pytest.mark.anyio
async def test_create_rejects_a_stale_audience_confirmation() -> None:
    app, db, _ = _app_and_db()
    save_subscription(db, email="list@example.com", unit_sizes={2}, source="public website")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/openings", json=_opening_payload(expected=0))

    assert response.status_code == 409
    assert response.json()["audienceCount"] == 1
    assert db.scalar(select(Opening)) is None


def test_selected_applications_are_not_notified() -> None:
    _, db, _ = _app_and_db()
    application = _application("selected@example.com")
    opening = Opening(
        unit_size_bedrooms=2,
        housing_charge_cents=120_000,
        application_open_date=date(2026, 1, 1),
        application_close_date=date(2026, 1, 15),
        move_in_date=date(2026, 2, 1),
        published_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    db.add_all([application, opening])
    db.flush()
    db.add(
        ApplicationParticipation(
            application_id=application.id,
            opening_id=opening.id,
            applied_at=datetime(2026, 1, 1, tzinfo=UTC),
            outcome=OpeningOutcome.SELECTED,
        )
    )
    db.commit()

    from app.services.vacancy_notifications import opening_audience

    assert opening_audience(db, 2).total == 0


def test_applications_due_for_retention_are_not_notified() -> None:
    _, db, _ = _app_and_db()
    expired = _application("expired@example.com")
    expired.retention_due_on = date(2000, 1, 1)
    db.add(expired)
    db.commit()

    from app.services.vacancy_notifications import opening_audience

    assert opening_audience(db, 2).total == 0
