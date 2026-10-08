from datetime import UTC, datetime, timedelta

import pytest
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import select

from app.api.session_cookie import SESSION_COOKIE_NAMES
from app.core.time import pacific_today
from app.db.models import (
    Application,
    ApplicationParticipation,
    EmailDelivery,
    EmailDeliveryState,
    Opening,
    OpeningOutcome,
    PasswordlessIdentityKind,
    User,
    UserRole,
)
from app.services.auth.passwordless import create_browser_session
from app.services.email.outbox import email_queue_status, retry_queued_emails
from app.services.email.sender import CapturedEmailSender, EmailRetryableError
from app.services.maintenance import get_outbox_runner
from app.services.openings.notifications import (
    queue_due_unsuccessful_notices,
)
from app.services.openings.selection import confirm_no_household_selected
from tests.applicant.support import app_and_db, sample_answers
from tests.db_support import memory_session


class FailingEmailSender:
    def send(self, _message) -> str:
        raise RuntimeError("synthetic delivery failure")


class RetryableEmailSender:
    def send(self, _message) -> str:
        raise EmailRetryableError("synthetic temporary failure")


def _db():
    return memory_session()


def _opening(db, *, archived: bool) -> Opening:
    today = pacific_today()
    opening = Opening(
        unit_size_bedrooms=2,
        housing_charge_cents=125_000,
        application_open_date=today - timedelta(days=30),
        application_close_date=today - timedelta(days=10),
        move_in_date=today if archived else today + timedelta(days=10),
        published_at=datetime.now(UTC),
        decided_at=datetime.now(UTC) if archived else None,
    )
    db.add(opening)
    db.flush()
    return opening


def _application(db, email: str) -> Application:
    application = Application(
        primary_email=email,
        applicant_name="Synthetic Applicant",
        raw_row={},
        raw_row_hash=email,
        normalized={},
        submitted_at=datetime.now(UTC),
    )
    db.add(application)
    db.flush()
    return application


def _participate(
    db, application: Application, opening: Opening, outcome: OpeningOutcome | None
) -> ApplicationParticipation:
    participation = ApplicationParticipation(
        application_id=application.id,
        opening_id=opening.id,
        applied_at=datetime.now(UTC),
        outcome=outcome,
    )
    db.add(participation)
    db.commit()
    return participation


def test_notice_waits_until_every_active_opening_has_a_decision() -> None:
    db = _db()
    sender = CapturedEmailSender()
    application = _application(db, "applicant@example.com")
    archived = _opening(db, archived=True)
    closed = _opening(db, archived=False)
    closed.unit_size_bedrooms = 3
    first = _participate(db, application, archived, OpeningOutcome.UNSUCCESSFUL)
    second = _participate(db, application, closed, None)

    assert queue_due_unsuccessful_notices(db) == 0
    assert retry_queued_emails(db, sender).accepted == 0

    closed.decided_at = datetime.now(UTC)
    second.outcome = OpeningOutcome.UNSUCCESSFUL
    db.commit()
    assert queue_due_unsuccessful_notices(db) == 1
    assert retry_queued_emails(db, sender).accepted == 1
    assert len(sender.messages) == 1
    assert "time and care you put into your application" in sender.messages[0].text_body
    assert "your household was not selected" in sender.messages[0].text_body
    assert "the 2-bedroom home" in sender.messages[0].text_body
    assert " or the 3-bedroom home" in sender.messages[0].text_body
    assert "move-in)" in sender.messages[0].text_body
    assert "applying for housing takes time and effort" in sender.messages[0].text_body
    assert "all the best in your housing search" in sender.messages[0].text_body
    assert "https://www.pentacoop.com/apply.html" in sender.messages[0].text_body
    assert first.unsuccessful_notified_at is not None
    assert second.unsuccessful_notified_at is not None


def test_notice_is_not_sent_to_an_application_selected_for_any_opening() -> None:
    db = _db()
    sender = CapturedEmailSender()
    application = _application(db, "selected@example.com")
    first = _opening(db, archived=True)
    second = _opening(db, archived=True)
    _participate(db, application, first, OpeningOutcome.SELECTED)
    _participate(db, application, second, OpeningOutcome.UNSUCCESSFUL)

    assert queue_due_unsuccessful_notices(db) == 0
    assert retry_queued_emails(db, sender).accepted == 0
    assert sender.messages == []


def test_accepted_notice_is_idempotent_if_marking_is_replayed() -> None:
    db = _db()
    sender = CapturedEmailSender()
    application = _application(db, "applicant@example.com")
    opening = _opening(db, archived=True)
    participation = _participate(
        db, application, opening, OpeningOutcome.UNSUCCESSFUL
    )

    assert queue_due_unsuccessful_notices(db) == 1
    assert retry_queued_emails(db, sender).accepted == 1
    participation.unsuccessful_notified_at = None
    db.commit()
    assert queue_due_unsuccessful_notices(db) == 0
    assert retry_queued_emails(db, sender).accepted == 0
    assert len(sender.messages) == 1
    assert participation.unsuccessful_notified_at is not None


@pytest.mark.parametrize("failing_sender", [FailingEmailSender, RetryableEmailSender])
def test_failed_notice_is_retried_without_marking_the_applicant_notified(failing_sender) -> None:
    db = _db()
    application = _application(db, "applicant@example.com")
    opening = _opening(db, archived=True)
    participation = _participate(
        db, application, opening, OpeningOutcome.UNSUCCESSFUL
    )

    assert queue_due_unsuccessful_notices(db) == 1
    assert retry_queued_emails(db, failing_sender()).accepted == 0
    assert participation.unsuccessful_notified_at is None

    sender = CapturedEmailSender()
    assert queue_due_unsuccessful_notices(db) == 1
    assert retry_queued_emails(db, sender).accepted == 1
    assert len(sender.messages) == 1
    assert participation.unsuccessful_notified_at is not None


@pytest.mark.anyio
@pytest.mark.parametrize("combined_first", [True, False])
async def test_reenrollment_supersedes_an_older_failed_closeout_in_either_drain_order(combined_first):
    app, db, sender = app_and_db()
    app.dependency_overrides[get_outbox_runner] = lambda: (
        lambda provider: retry_queued_emails(db, provider, retry_failures=False)
    )
    first = db.scalar(select(Opening))
    admin = User(email="admin@example.com", display_name="Synthetic Admin", role=UserRole.ADMIN, is_active=True)
    db.add(admin)
    db.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        assert (await client.post("/applicant/submissions", json={
            "answers": sample_answers(), "openingIds": [first.id], "declarationAccepted": True,
        })).status_code == 201
        application = db.scalar(select(Application))
        first.application_close_date = pacific_today() - timedelta(days=1)
        db.commit()
        assert confirm_no_household_selected(db, first, decided_by=admin) == 1
        assert retry_queued_emails(db, RetryableEmailSender()).accepted == 0
        old_notice = db.scalar(select(EmailDelivery).where(EmailDelivery.message_kind == "application_unsuccessful"))

        second = _opening(db, archived=False)
        second.unit_size_bedrooms = 3
        second.application_close_date = pacific_today() + timedelta(days=10)
        issued = create_browser_session(db, identity_kind=PasswordlessIdentityKind.APPLICANT, application_id=application.id)
        db.commit()
        client.cookies.set(SESSION_COOKIE_NAMES[PasswordlessIdentityKind.APPLICANT], issued.token)
        client.headers["X-Penta-Identity"] = f"applicant:{application.id}"
        reenrolled = await client.post("/applicant/application/submit", json={
            "answers": sample_answers(), "openingIds": [first.id, second.id],
            "declarationAccepted": True, "baseRevision": application.working_revision,
        })
        assert reenrolled.status_code == 200

    assert old_notice.state == EmailDeliveryState.QUEUED
    assert queue_due_unsuccessful_notices(db) == 0
    second.application_close_date = pacific_today() - timedelta(days=1)
    db.commit()
    assert confirm_no_household_selected(db, second, decided_by=admin) == 1
    assert retry_queued_emails(db, sender, retry_failures=not combined_first).accepted == 1
    assert queue_due_unsuccessful_notices(db) == 0
    assert retry_queued_emails(db, sender).accepted == 0
    notices = [message for message in sender.messages if message.kind == "application_unsuccessful"]
    assert len(notices) == 1
    assert "the 2-bedroom home" in notices[0].text_body
    assert "the 3-bedroom home" in notices[0].text_body
    assert old_notice.state == EmailDeliveryState.FAILED
    assert old_notice.last_error_code == "OutcomeNoLongerDue"
    assert old_notice.retry_intent is None
    assert email_queue_status(db).recent_failed == 0
    assert all(row.unsuccessful_notified_at is not None for row in db.scalars(select(ApplicationParticipation)))


def _failed_closeout():
    db = _db()
    application = _application(db, "synthetic@example.com")
    opening = _opening(db, archived=True)
    participation = _participate(db, application, opening, OpeningOutcome.UNSUCCESSFUL)
    assert queue_due_unsuccessful_notices(db) == 1
    assert retry_queued_emails(db, RetryableEmailSender()).accepted == 0
    return db, application, participation


@pytest.mark.parametrize("change", ["pending", "withdrawn", "selected"])
def test_retry_cancels_a_closeout_that_lost_lifecycle_authority(change):
    db, application, original = _failed_closeout()
    if change == "withdrawn":
        application.withdrawn_at = datetime.now(UTC)
    else:
        later = _opening(db, archived=change == "selected")
        participation = _participate(db, application, later, OpeningOutcome.SELECTED if change == "selected" else None)
    db.commit()
    sender = CapturedEmailSender()
    assert retry_queued_emails(db, sender).accepted == 0
    assert sender.messages == []
    assert original.unsuccessful_notified_at is None
    delivery = db.scalar(select(EmailDelivery))
    assert delivery.last_error_code == "OutcomeNoLongerDue"
    assert email_queue_status(db).recent_failed == 0
    if change == "pending":
        # Withdrawing from the undecided opening makes the original notice due again.
        participation.withdrawn_at = datetime.now(UTC)
        db.commit()
        assert queue_due_unsuccessful_notices(db) == 1
        assert retry_queued_emails(db, sender).accepted == 1
        assert original.unsuccessful_notified_at is not None


def test_participation_during_delivery_does_not_erase_the_accepted_outcome_receipt():
    db, application, first = _failed_closeout()
    later = []

    class ReenrollingSender(CapturedEmailSender):
        def send(self, message):
            assert not db.in_transaction()  # Preparation never holds a writer across provider I/O.
            opening = _opening(db, archived=False)
            opening.unit_size_bedrooms = 3
            later.append(_participate(db, application, opening, None))
            return super().send(message)

    assert retry_queued_emails(db, ReenrollingSender()).accepted == 1
    assert first.unsuccessful_notified_at is not None
    assert later[0].unsuccessful_notified_at is None
    assert queue_due_unsuccessful_notices(db) == 0
    opening = db.get(Opening, later[0].opening_id)
    opening.decided_at = datetime.now(UTC)
    later[0].outcome = OpeningOutcome.UNSUCCESSFUL
    db.commit()
    assert queue_due_unsuccessful_notices(db) == 1
    sender = CapturedEmailSender()
    assert retry_queued_emails(db, sender).accepted == 1
    assert "the 3-bedroom home" in sender.messages[0].text_body
    assert "the 2-bedroom home" not in sender.messages[0].text_body
    assert later[0].unsuccessful_notified_at is not None


def test_queued_notices_are_scoped_to_the_finalized_opening_participants() -> None:
    db = _db()
    sender = CapturedEmailSender()
    opening = _opening(db, archived=True)
    target = _application(db, "target@example.com")
    unrelated = _application(db, "unrelated@example.com")
    target_participation = _participate(
        db, target, opening, OpeningOutcome.UNSUCCESSFUL
    )
    unrelated_participation = _participate(
        db, unrelated, opening, OpeningOutcome.UNSUCCESSFUL
    )

    assert queue_due_unsuccessful_notices(db, application_ids={target.id}) == 1
    assert retry_queued_emails(db, sender).accepted == 1
    assert [message.to for message in sender.messages] == [("target@example.com",)]
    assert target_participation.unsuccessful_notified_at is not None
    assert unrelated_participation.unsuccessful_notified_at is None


def test_no_work_closeout_sweep_performs_no_application_writes() -> None:
    from sqlalchemy import event

    db = _db()
    opening = _opening(db, archived=False)
    for index in range(100):
        application = _application(db, f"synthetic-{index}@example.test")
        _participate(db, application, opening, None)
    statements = []
    commits = []
    def count(_connection, _cursor, statement, *_args):
        statements.append(statement.lstrip().split()[0].upper())
    def committed(_session):
        commits.append(True)
    event.listen(db.bind, "before_cursor_execute", count)
    event.listen(db, "after_commit", committed)
    try:
        assert queue_due_unsuccessful_notices(db) == 0
    finally:
        event.remove(db.bind, "before_cursor_execute", count)
        event.remove(db, "after_commit", committed)
    assert statements == ["SELECT"]
    assert commits == []


def test_expired_unsuccessful_application_never_queues_a_notice() -> None:
    db = _db()
    application = _application(db, "expired@example.test")
    opening = _opening(db, archived=True)
    _participate(db, application, opening, OpeningOutcome.UNSUCCESSFUL)
    application.retention_due_on = pacific_today()
    db.commit()
    assert queue_due_unsuccessful_notices(db) == 0
    sender = CapturedEmailSender()
    retry_queued_emails(db, sender)
    assert sender.messages == []
