from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.time import as_utc
from app.db.models import (
    Application,
    Base,
    EmailDelivery,
    EmailDeliveryState,
    MagicLinkPurpose,
    MagicLinkToken,
    PasswordlessIdentityKind,
    User,
    UserRole,
)
from app.services.email_outbox import email_queue_status, retry_queued_emails
from app.services.email_sender import CapturedEmailSender, EmailQuotaExceededError
from app.services.magic_link_delivery import (
    EmailSendOutcome,
    send_application_unavailable,
    send_magic_link,
)


class QuotaBlockedSender:
    def send(self, _message) -> str:
        raise EmailQuotaExceededError("synthetic quota rejection")


def _db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)()


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


def test_new_magic_link_request_supersedes_queued_credential_intent() -> None:
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
    assert queued_delivery.state == EmailDeliveryState.FAILED
    assert queued_delivery.last_error_code == "Superseded"
    assert queued_delivery.retry_intent is None
    assert email_queue_status(db).count == 0
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
