from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import sessionmaker

from app.core.time import as_utc
from app.db.models import (
    Application,
    EmailDelivery,
    EmailDeliveryState,
    MagicLinkPurpose,
    MagicLinkToken,
    PasswordlessIdentityKind,
    User,
    UserRole,
)
from app.services.email import outbox
from app.services.email.delivery import ATTEMPT_LEASE, claim_delivery_attempt
from app.services.email.outbox import email_queue_status, retry_queued_emails
from app.services.email.sender import CapturedEmailSender, EmailQuotaExceededError
from app.services.email.transactional import (
    EmailSendOutcome,
    send_application_unavailable,
    send_magic_link,
)
from tests.db_support import memory_engine, memory_session


class QuotaBlockedSender:
    def send(self, _message) -> str:
        raise EmailQuotaExceededError("synthetic quota rejection")


class TerminalFailureSender:
    def send(self, _message) -> str:
        raise ValueError("synthetic terminal failure")


def _db():
    return memory_session()


def test_obsolete_submission_confirmation_does_not_block_other_mail() -> None:
    db = _db()
    application = Application(primary_email="withdrawn@example.com", raw_row={}, raw_row_hash="withdrawn")
    db.add(application)
    db.flush()
    confirmation = EmailDelivery(message_kind="application_confirmation", application_id=application.id,
        recipient_kind=PasswordlessIdentityKind.APPLICANT, state=EmailDeliveryState.QUEUED,
        retry_intent={"type": "application_confirmation", "submitted": True})
    db.add_all([confirmation, EmailDelivery(message_kind="application_unavailable",
        recipient_kind=PasswordlessIdentityKind.APPLICANT, recipient_email="other@example.com",
        state=EmailDeliveryState.QUEUED, retry_intent={"type": "application_unavailable"})])
    db.commit()
    sender = CapturedEmailSender()
    assert retry_queued_emails(db, sender).accepted == 1
    assert sender.messages[0].to == ("other@example.com",)
    assert confirmation.state == EmailDeliveryState.FAILED
    assert confirmation.last_error_code == "SubmissionNoLongerDue"
    assert db.scalar(select(MagicLinkToken)) is None
    assert email_queue_status(db).recent_failed == 0


def test_preparation_failure_rolls_back_credentials_and_continues_batch(monkeypatch) -> None:
    db = _db()
    application = Application(primary_email="first@example.com", raw_row={}, raw_row_hash="first")
    db.add(application)
    db.flush()
    confirmation = EmailDelivery(message_kind="application_confirmation", application_id=application.id,
        recipient_kind=PasswordlessIdentityKind.APPLICANT, state=EmailDeliveryState.QUEUED,
        retry_intent={"type": "application_confirmation", "submitted": False})
    db.add_all([confirmation, EmailDelivery(message_kind="application_unavailable",
        recipient_kind=PasswordlessIdentityKind.APPLICANT, recipient_email="other@example.com",
        state=EmailDeliveryState.QUEUED, retry_intent={"type": "application_unavailable"})])
    db.commit()

    def fail_template(**_kwargs):
        assert db.scalar(select(MagicLinkToken)) is not None
        raise ValueError("synthetic private content must not be retained")

    monkeypatch.setattr(outbox, "application_confirmation_email", fail_template)
    sender = CapturedEmailSender()
    assert retry_queued_emails(db, sender).accepted == 1
    assert sender.messages[0].to == ("other@example.com",)
    assert confirmation.state == EmailDeliveryState.FAILED
    assert confirmation.attempt_count == 1
    assert confirmation.last_error_code == "Preparation:ValueError"
    assert confirmation.magic_link_token_id is None
    assert db.scalar(select(MagicLinkToken)) is None
    assert email_queue_status(db).recent_failed == 1


def test_an_overlapping_outbox_worker_cannot_send_the_same_delivery() -> None:
    factory = sessionmaker(bind=memory_engine(), autoflush=False)
    now = datetime.now(UTC)
    with factory() as db:
        db.add(EmailDelivery(
            idempotency_key="synthetic-overlap", message_kind="application_unavailable",
            recipient_kind=PasswordlessIdentityKind.APPLICANT, recipient_email="a@example.com",
            state=EmailDeliveryState.QUEUED, retry_intent={"type": "application_unavailable"},
        ))
        db.commit()

    class OverlappingSender(CapturedEmailSender):
        def send(self, message):
            with factory() as competing:
                assert retry_queued_emails(competing, self, now=now).accepted == 0
            return super().send(message)

    sender = OverlappingSender()
    with factory() as db:
        assert retry_queued_emails(db, sender, now=now).accepted == 1
        delivery = db.scalar(select(EmailDelivery))
        assert delivery.attempt_count == 1
        assert delivery.state == EmailDeliveryState.ACCEPTED
    assert len(sender.messages) == 1


def test_an_abandoned_email_attempt_becomes_retryable_after_its_lease() -> None:
    db = _db()
    now = datetime.now(UTC)
    delivery = EmailDelivery(
        message_kind="application_unavailable", recipient_kind=PasswordlessIdentityKind.APPLICANT,
        recipient_email="a@example.com", state=EmailDeliveryState.QUEUED,
        retry_intent={"type": "application_unavailable"},
    )
    db.add(delivery)
    db.commit()
    delivery_id = delivery.id
    assert claim_delivery_attempt(db, delivery_id, now=now) is not None
    assert claim_delivery_attempt(db, delivery_id, now=now + timedelta(seconds=1)) is None
    sender = CapturedEmailSender()
    assert retry_queued_emails(db, sender, now=now + ATTEMPT_LEASE).accepted == 1
    assert len(sender.messages) == 1
    db.refresh(delivery)
    assert delivery.attempt_count == 2


def test_later_batch_messages_receive_fresh_attempt_times(monkeypatch) -> None:
    factory = sessionmaker(bind=memory_engine(), autoflush=False)
    start = datetime(2026, 8, 26, 18, tzinfo=UTC)
    clock_time = start

    class Clock:
        @staticmethod
        def now(_timezone):
            return clock_time

    monkeypatch.setattr(outbox, "datetime", Clock)
    with factory() as db:
        for recipient in ("first@example.com", "second@example.com"):
            db.add(EmailDelivery(message_kind="application_unavailable",
                recipient_kind=PasswordlessIdentityKind.APPLICANT, recipient_email=recipient,
                state=EmailDeliveryState.QUEUED, retry_intent={"type": "application_unavailable"}))
        db.commit()

    class AdvancingSender(CapturedEmailSender):
        def send(self, message):
            nonlocal clock_time
            if not self.messages:
                clock_time = start + ATTEMPT_LEASE + timedelta(seconds=1)
            else:
                with factory() as competing:
                    assert claim_delivery_attempt(competing, 2, now=clock_time) is None
            return super().send(message)

    with factory() as db:
        assert retry_queued_emails(db, AdvancingSender()).accepted == 2
        assert as_utc(db.get(EmailDelivery, 2).last_attempt_at) == clock_time


def test_prepared_attempt_does_not_adopt_a_replacement_after_commit(monkeypatch) -> None:
    factory = sessionmaker(bind=memory_engine(), autoflush=False)
    now = datetime(2026, 8, 26, 18, tzinfo=UTC)
    with factory() as db:
        db.add(EmailDelivery(message_kind="application_unavailable",
            recipient_kind=PasswordlessIdentityKind.APPLICANT, recipient_email="synthetic@example.com",
            state=EmailDeliveryState.QUEUED, retry_intent={"type": "application_unavailable"}))
        db.commit()
    original_attempt = outbox.attempt_reserved_delivery

    def replace_before_network(db, sender, attempt, message, **kwargs):
        with factory() as replacement:
            assert claim_delivery_attempt(replacement, attempt.delivery_id, now=now + ATTEMPT_LEASE) is not None
        return original_attempt(db, sender, attempt, message, **kwargs)

    monkeypatch.setattr(outbox, "attempt_reserved_delivery", replace_before_network)
    with factory() as db:
        assert retry_queued_emails(db, CapturedEmailSender(), now=now).accepted == 0
        delivery = db.get(EmailDelivery, 1)
        assert delivery.attempt_count == 2
        assert delivery.state == EmailDeliveryState.QUEUED


def test_a_late_provider_failure_cannot_revive_a_cancelled_intent() -> None:
    factory = sessionmaker(bind=memory_engine(), autoflush=False)
    now = datetime.now(UTC)
    with factory() as db:
        db.add(EmailDelivery(
            message_kind="application_unavailable", recipient_kind=PasswordlessIdentityKind.APPLICANT,
            recipient_email="a@example.com", state=EmailDeliveryState.QUEUED,
            retry_intent={"type": "application_unavailable"},
        ))
        db.commit()

    class CancellingSender:
        def send(self, _message):
            with factory() as cancellation:
                cancellation.execute(update(EmailDelivery).values(
                    state=EmailDeliveryState.FAILED, retry_intent=None, last_error_code="ApplicationWithdrawn",
                ))
                cancellation.commit()
            raise EmailQuotaExceededError("synthetic provider failure after cancellation")

    with factory() as db:
        summary = retry_queued_emails(db, CancellingSender(), now=now)
        assert summary.accepted == 0
        assert summary.still_queued == 0
        delivery = db.scalar(select(EmailDelivery))
        assert delivery.state == EmailDeliveryState.FAILED
        assert delivery.retry_intent is None
        assert delivery.last_error_code == "ApplicationWithdrawn"


def test_a_late_attempt_cannot_replace_a_newer_attempt_outcome() -> None:
    factory = sessionmaker(bind=memory_engine(), autoflush=False)
    now = datetime.now(UTC)
    with factory() as db:
        db.add(EmailDelivery(
            message_kind="application_unavailable", recipient_kind=PasswordlessIdentityKind.APPLICANT,
            recipient_email="a@example.com", state=EmailDeliveryState.QUEUED,
            retry_intent={"type": "application_unavailable"},
        ))
        db.commit()

    class DelayedSender:
        def send(self, _message):
            with factory() as newer:
                assert retry_queued_emails(newer, CapturedEmailSender(), now=now + ATTEMPT_LEASE).accepted == 1
            raise EmailQuotaExceededError("synthetic obsolete response")

    with factory() as db:
        assert retry_queued_emails(db, DelayedSender(), now=now).accepted == 0
        delivery = db.scalar(select(EmailDelivery))
        assert delivery.attempt_count == 2
        assert delivery.state == EmailDeliveryState.ACCEPTED
        assert delivery.last_error_code is None


def test_quota_blocked_magic_link_retries_with_a_fresh_credential() -> None:
    db = _db()
    application = Application(
        primary_email="applicant@example.com",
        raw_row={},
        raw_row_hash="synthetic",
        normalized={},
    )
    db.add(application)
    db.commit()
    now = datetime(2026, 8, 26, 12, tzinfo=UTC)

    outcome = send_magic_link(
        db,
        QuotaBlockedSender(),
        identity_kind=PasswordlessIdentityKind.APPLICANT,
        purpose=MagicLinkPurpose.APPLICANT_ACCESS,
        email=application.primary_email,
        recipient_id=application.id,
        application_id=application.id,
        now=now,
    )

    assert outcome == EmailSendOutcome.FAILED
    delivery = db.scalar(select(EmailDelivery))
    assert delivery is not None
    assert delivery.state == EmailDeliveryState.QUEUED
    assert delivery.quota_blocked is True
    assert delivery.retry_intent is not None
    assert "token" not in str(delivery.retry_intent).lower()
    assert application.primary_email not in str(delivery.retry_intent)
    first_token = db.scalar(select(MagicLinkToken))
    assert first_token is not None
    assert first_token.revoked_at is not None
    assert as_utc(first_token.revoked_at) == now
    status = email_queue_status(db)
    assert (status.count, status.quota_blocked) == (1, 1)

    sender = CapturedEmailSender()
    summary = retry_queued_emails(db, sender, now=now + timedelta(days=1))

    assert summary.accepted == 1
    assert email_queue_status(db).count == 0
    db.refresh(delivery)
    assert delivery.state == EmailDeliveryState.ACCEPTED
    assert delivery.retry_intent is None
    tokens = db.scalars(select(MagicLinkToken).order_by(MagicLinkToken.id)).all()
    assert len(tokens) == 2
    assert tokens[0].revoked_at is not None
    assert as_utc(tokens[0].revoked_at) == now
    assert tokens[1].revoked_at is None
    assert as_utc(tokens[1].created_at) == now + timedelta(days=1)
    assert len(sender.messages) == 1


def test_targetless_access_update_retries_without_retaining_recipient_email() -> None:
    db = _db()
    now = datetime(2026, 8, 26, 12, tzinfo=UTC)

    assert not send_application_unavailable(
        db,
        QuotaBlockedSender(),
        "unknown@example.com",
        now=now,
    )
    delivery = db.scalar(select(EmailDelivery))
    assert delivery is not None
    assert delivery.state == EmailDeliveryState.QUEUED
    assert delivery.recipient_email == "unknown@example.com"

    sender = CapturedEmailSender()
    assert retry_queued_emails(db, sender, now=now + timedelta(days=1)).accepted == 1

    db.refresh(delivery)
    assert sender.messages[0].to == ("unknown@example.com",)
    assert delivery.recipient_email is None
    assert delivery.retry_intent is None


def test_targetless_terminal_failure_retains_recipient_for_admin_review() -> None:
    db = _db()

    assert not send_application_unavailable(
        db,
        TerminalFailureSender(),
        "unknown@example.com",
    )

    delivery = db.scalar(select(EmailDelivery))
    assert delivery is not None
    assert delivery.state == EmailDeliveryState.FAILED
    assert delivery.recipient_email == "unknown@example.com"
    assert delivery.last_error_code == "ValueError"


def test_new_magic_link_request_preserves_queued_credential_intent() -> None:
    db = _db()
    application = Application(
        primary_email="applicant@example.com",
        raw_row={},
        raw_row_hash="synthetic",
        normalized={},
    )
    db.add(application)
    db.commit()
    now = datetime(2026, 8, 26, 12, tzinfo=UTC)

    assert (
        send_magic_link(
            db,
            QuotaBlockedSender(),
            identity_kind=PasswordlessIdentityKind.APPLICANT,
            purpose=MagicLinkPurpose.APPLICANT_ACCESS,
            email=application.primary_email,
            recipient_id=application.id,
            application_id=application.id,
            now=now,
        )
        == EmailSendOutcome.FAILED
    )
    queued_delivery = db.scalar(select(EmailDelivery))
    assert queued_delivery is not None

    sender = CapturedEmailSender()
    assert (
        send_magic_link(
            db,
            sender,
            identity_kind=PasswordlessIdentityKind.APPLICANT,
            purpose=MagicLinkPurpose.APPLICANT_ACCESS,
            email=application.primary_email,
            recipient_id=application.id,
            application_id=application.id,
            now=now + timedelta(minutes=1),
            enforce_request_limits=False,
        )
        == EmailSendOutcome.SENT
    )

    db.refresh(queued_delivery)
    assert queued_delivery.state == EmailDeliveryState.QUEUED
    assert queued_delivery.retry_intent is not None
    assert email_queue_status(db).count == 1
    assert len(sender.messages) == 1


def test_committee_magic_link_retry_uses_the_current_user_record() -> None:
    db = _db()
    user = User(
        email="committee@example.com",
        display_name="Synthetic Member",
        role=UserRole.MEMBER,
    )
    db.add(user)
    db.commit()
    now = datetime(2026, 8, 26, 12, tzinfo=UTC)

    assert (
        send_magic_link(
            db,
            QuotaBlockedSender(),
            identity_kind=PasswordlessIdentityKind.COMMITTEE,
            purpose=MagicLinkPurpose.COMMITTEE_ACCESS,
            email=user.email,
            recipient_id=user.id,
            user_id=user.id,
            now=now,
        )
        == EmailSendOutcome.FAILED
    )
    user.email = "updated@example.com"
    db.commit()

    sender = CapturedEmailSender()
    assert retry_queued_emails(db, sender, now=now + timedelta(days=1)).accepted == 1
    assert sender.messages[0].to == (user.email,)
