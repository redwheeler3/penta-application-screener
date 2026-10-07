"""Signups and delivery acknowledgements preserve the current notification request."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier

import pytest
from sqlalchemy import create_engine, event, select, update
from sqlalchemy.orm import sessionmaker

from app.core.time import pacific_today
from app.db.models import (
    Application,
    Base,
    EmailDelivery,
    EmailDeliveryState,
    MagicLinkToken,
    Opening,
    VacancySubscription,
)
from app.services.email.delivery import ATTEMPT_LEASE, claim_delivery_attempt
from app.services.email.outbox import email_queue_status, retry_queued_emails
from app.services.email.sender import (
    CapturedEmailSender,
    EmailQuotaExceededError,
    EmailRetryableError,
)
from app.services.email.subscription_delivery import reserve_subscription_consent
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
        if edit == "resubscribe":
            assert updated_ids[0] > subscription_id
        else:
            assert updated_ids == [subscription_id]
        subscription = db.get(VacancySubscription, updated_ids[0], populate_existing=True)
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
        # Exercise an existing legacy collision as well as new monotonic allocation.
        db.execute(update(VacancySubscription).where(VacancySubscription.id == other.id).values(id=old_id)
            .execution_options(synchronize_session=False))
        db.commit()
        other = db.get(VacancySubscription, old_id, populate_existing=True)
        sender = CapturedEmailSender()
        result = retry_queued_emails(db, sender, now=now)
        assert result.accepted == (1 if overlap else 0)
        assert db.get(VacancySubscription, other.id) is not None


def queue_another_opening(db, now):
    today = pacific_today(now=now)
    opening = Opening(unit_size_bedrooms=2, housing_charge_cents=100_000,
        application_open_date=today, application_close_date=today + timedelta(days=10),
        move_in_date=today + timedelta(days=30), published_at=now)
    db.add(opening)
    db.flush()
    queue_opening_notifications(db, opening, opening_audience(db, 2))
    db.commit()
    return opening


@pytest.mark.parametrize("overlap", [False, True])
@pytest.mark.parametrize("scheduled_competitor", [False, True])
def test_two_workers_reserve_one_consent_but_keep_independent_application_authority(
    request_sessions, overlap, scheduled_competitor,
):
    with request_sessions() as db:
        subscription_id, now = queue_notification(db, overlap=overlap)
        queue_another_opening(db, now)
        ids = db.scalars(select(EmailDelivery.id).order_by(EmailDelivery.id)).all()
    competing_sender = CapturedEmailSender()
    class OverlappingSender(CapturedEmailSender):
        def send(self, message):
            with request_sessions() as competing:
                result = retry_queued_emails(competing, competing_sender, now=now,
                    retry_failures=scheduled_competitor)
                assert result.accepted == (1 if overlap else 0)
                second = competing.get(EmailDelivery, ids[1], populate_existing=True)
                assert second.attempt_count == (1 if overlap else 0)
                if not overlap:
                    assert second.state == EmailDeliveryState.QUEUED
                    assert competing.scalar(select(MagicLinkToken)) is None
                assert competing.get(VacancySubscription, subscription_id) is not None
            return super().send(message)
    sender = OverlappingSender()
    with request_sessions() as db:
        assert retry_queued_emails(db, sender, now=now, retry_failures=False).accepted == 1
        assert db.get(VacancySubscription, subscription_id, populate_existing=True) is None
    messages = sender.messages + competing_sender.messages
    assert len(messages) == (2 if overlap else 1)
    if overlap:
        assert sum("also completes your one-time" in message.text_body for message in messages) == 1
        assert competing_sender.messages[0].kind == "application_opening"


@pytest.mark.parametrize("failure", [EmailQuotaExceededError, EmailRetryableError])
def test_retryable_owner_holds_consent_until_daily_retry(request_sessions, failure):
    class FailingSender:
        def send(self, _message):
            raise failure("Synthetic temporary failure")
    with request_sessions() as db:
        subscription_id, now = queue_notification(db, overlap=False)
        retry_queued_emails(db, FailingSender(), now=now, retry_failures=False)
        owner = db.scalar(select(EmailDelivery))
        owner_id = owner.id
        assert owner.retry_intent["subscription_consented_at"]
        queue_another_opening(db, now)
        sender = CapturedEmailSender()
        retry_queued_emails(db, sender, now=now + timedelta(seconds=1), retry_failures=False)
        assert sender.messages == []
        assert db.get(EmailDelivery, owner_id, populate_existing=True).attempt_count == 1
        deferred = db.scalar(select(EmailDelivery).where(EmailDelivery.id != owner_id))
        assert deferred.attempt_count == 0
        assert deferred.state == EmailDeliveryState.QUEUED
        assert db.get(VacancySubscription, subscription_id) is not None
        assert retry_queued_emails(db, sender, now=now + timedelta(days=1)).accepted == 1
        assert len(sender.messages) == 1
        assert db.get(VacancySubscription, subscription_id, populate_existing=True) is None


def test_application_notice_sends_while_list_only_owner_waits_for_retry(request_sessions):
    class FailingSender:
        def send(self, _message):
            raise EmailRetryableError("Synthetic temporary failure")
    with request_sessions() as db:
        subscription_id, now = queue_notification(db, overlap=False)
        retry_queued_emails(db, FailingSender(), now=now, retry_failures=False)
        db.add(Application(primary_email="synthetic@example.com", raw_row={}, raw_row_hash="synthetic",
            submitted_at=now, retention_due_on=pacific_today(now=now) + timedelta(days=365)))
        db.commit()
        queue_another_opening(db, now)
        sender = CapturedEmailSender()
        assert retry_queued_emails(db, sender, now=now + timedelta(seconds=1), retry_failures=False).accepted == 1
        assert sender.messages[0].kind == "application_opening"
        assert "also completes your one-time" not in sender.messages[0].text_body
        assert db.get(VacancySubscription, subscription_id) is not None


@pytest.mark.parametrize("release", ["closed", "terminal", "cancelled"])
def test_unavailable_consent_owner_allows_waiting_delivery(request_sessions, release):
    class FailingSender:
        def send(self, _message):
            raise EmailRetryableError("Synthetic temporary failure")
    with request_sessions() as db:
        subscription_id, now = queue_notification(db, overlap=False)
        retry_queued_emails(db, FailingSender(), now=now, retry_failures=False)
        owner = db.scalar(select(EmailDelivery))
        if release == "closed":
            opening = db.get(Opening, owner.retry_intent["opening_id"])
            opening.application_close_date = pacific_today(now=now) - timedelta(days=1)
        else:
            owner.state = EmailDeliveryState.FAILED
            owner.retry_intent = None
            owner.last_error_code = "ApplicationWithdrawn" if release == "cancelled" else "ValueError"
        db.commit()
        queue_another_opening(db, now)
        sender = CapturedEmailSender()
        assert retry_queued_emails(db, sender, now=now, retry_failures=False).accepted == 1
        assert len(sender.messages) == 1
        assert db.get(VacancySubscription, subscription_id, populate_existing=True) is None


def test_expired_owner_attempt_lease_recovers_without_transferring_consent(request_sessions):
    with request_sessions() as db:
        subscription_id, now = queue_notification(db, overlap=False)
        owner = db.scalar(select(EmailDelivery))
        assert claim_delivery_attempt(db, owner.id, now=now, commit=False) is not None
        assert reserve_subscription_consent(db, owner, db.get(VacancySubscription, subscription_id), now=now)
        db.commit()
        queue_another_opening(db, now)
        sender = CapturedEmailSender()
        assert retry_queued_emails(db, sender, now=now, retry_failures=False).accepted == 0
        assert retry_queued_emails(db, sender, now=now + ATTEMPT_LEASE, retry_failures=False).accepted == 1
        assert len(sender.messages) == 1
        assert db.get(VacancySubscription, subscription_id, populate_existing=True) is None


@pytest.mark.parametrize("scheduled_competitor", [False, True])
def test_closing_an_opening_during_send_keeps_consent_with_the_live_attempt(
    request_sessions, scheduled_competitor,
):
    with request_sessions() as db:
        subscription_id, now = queue_notification(db, overlap=False)
        owner = db.scalar(select(EmailDelivery))
        owner_opening_id = owner.retry_intent["opening_id"]
        queue_another_opening(db, now)
        waiting_id = db.scalar(select(EmailDelivery.id).where(EmailDelivery.id != owner.id))

    competing_sender = CapturedEmailSender()
    class ClosingSender(CapturedEmailSender):
        def send(self, message):
            with request_sessions() as competing:
                opening = competing.get(Opening, owner_opening_id)
                opening.application_close_date = pacific_today(now=now) - timedelta(days=1)
                competing.commit()
                result = retry_queued_emails(competing, competing_sender, now=now,
                    retry_failures=scheduled_competitor)
                assert result.accepted == 0
                waiting = competing.get(EmailDelivery, waiting_id, populate_existing=True)
                assert waiting.attempt_count == 0
                assert waiting.state == EmailDeliveryState.QUEUED
                assert competing.get(VacancySubscription, subscription_id) is not None
            return super().send(message)

    sender = ClosingSender()
    with request_sessions() as db:
        assert retry_queued_emails(db, sender, now=now, retry_failures=False).accepted == 1
        assert db.get(VacancySubscription, subscription_id, populate_existing=True) is None
    assert len(sender.messages) == 1
    assert competing_sender.messages == []
