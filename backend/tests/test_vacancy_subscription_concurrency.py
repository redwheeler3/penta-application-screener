"""Signups and delivery acknowledgements preserve the current notification request."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app.core.time import pacific_today
from app.db.models import Application, Base, Opening, VacancySubscription
from app.services.email.outbox import email_queue_status, retry_queued_emails
from app.services.email.sender import CapturedEmailSender
from app.services.openings.subscriptions import delete_subscription, save_subscription
from app.services.openings.vacancy_notifications import (
    opening_audience,
    queue_opening_notifications,
)


@pytest.fixture
def request_sessions(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'subscriptions.db'}", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def pragmas(connection, _record):
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")

    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, autoflush=False)
    engine.dispose()


def test_competing_first_signups_both_succeed_with_one_subscription(request_sessions) -> None:
    ready = Barrier(2)

    def signup(size):
        with request_sessions() as db:
            ready.wait(timeout=5)
            return save_subscription(db, email="synthetic@example.com", unit_sizes={size}, source="public website").id

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(signup, size) for size in (2, 3)]
        ids = [future.result(timeout=5) for future in futures]
    assert ids[0] == ids[1]
    with request_sessions() as db:
        assert len(db.scalars(select(VacancySubscription)).all()) == 1


def queue_notification(db, *, overlap):
    now = datetime.now(UTC)
    today = pacific_today(now=now)
    subscription = save_subscription(db, email="synthetic@example.com", unit_sizes={2}, source="public website", consented_at=now)
    opening = Opening(
        unit_size_bedrooms=2, housing_charge_cents=100_000, application_open_date=today,
        application_close_date=today + timedelta(days=10), move_in_date=today + timedelta(days=30), published_at=now,
    )
    db.add(opening)
    if overlap:
        db.add(Application(
            primary_email=subscription.email, raw_row={}, raw_row_hash="synthetic", normalized={},
            submitted_at=now, retention_due_on=today + timedelta(days=365),
        ))
    db.commit()
    queue_opening_notifications(db, opening, opening_audience(db, 2))
    db.commit()
    return subscription.id, now


@pytest.mark.parametrize("overlap", [False, True])
@pytest.mark.parametrize("edit", ["replace", "resubscribe"])
def test_preferences_changed_during_delivery_survive_acceptance(request_sessions, overlap, edit) -> None:
    with request_sessions() as db:
        subscription_id, now = queue_notification(db, overlap=overlap)
        updated_ids = []

        class UpdatingSender:
            def send(self, _message):
                with request_sessions() as other:
                    if edit == "resubscribe":
                        delete_subscription(other, email="synthetic@example.com")
                    updated_ids.append(save_subscription(
                        other, email="synthetic@example.com", unit_sizes={3}, source="public website",
                        consented_at=now + timedelta(seconds=1),
                    ).id)
                return "synthetic-provider-id"

        summary = retry_queued_emails(db, UpdatingSender(), now=now)
        assert summary.accepted == 1
        assert updated_ids == [subscription_id]  # SQLite can reuse the deleted row ID.
        subscription = db.get(VacancySubscription, subscription_id, populate_existing=True)
        assert subscription is not None
        assert subscription.wants_three_bedroom is True
        assert subscription.wants_two_bedroom is False


@pytest.mark.parametrize("overlap", [False, True])
def test_changed_sizes_before_delivery_are_not_consumed_for_an_unmatched_home(request_sessions, overlap) -> None:
    with request_sessions() as db:
        subscription_id, now = queue_notification(db, overlap=overlap)
        save_subscription(db, email="synthetic@example.com", unit_sizes={3}, source="public website", consented_at=now + timedelta(seconds=1))
        sender = CapturedEmailSender()
        summary = retry_queued_emails(db, sender, now=now)
        assert summary.accepted == (1 if overlap else 0)
        assert len(sender.messages) == (1 if overlap else 0)
        assert db.get(VacancySubscription, subscription_id) is not None
        assert email_queue_status(db, now=now).recent_failed == 0


@pytest.mark.parametrize("overlap", [False, True])
def test_reused_subscription_id_does_not_consume_another_email_request(request_sessions, overlap) -> None:
    with request_sessions() as db:
        old_id, now = queue_notification(db, overlap=overlap)
        delete_subscription(db, email="synthetic@example.com")
        other = save_subscription(db, email="other@example.com", unit_sizes={2}, source="public website", consented_at=now + timedelta(seconds=1))
        assert other.id == old_id
        sender = CapturedEmailSender()
        result = retry_queued_emails(db, sender, now=now)
        assert result.accepted == (1 if overlap else 0)
        assert db.get(VacancySubscription, other.id) is not None
