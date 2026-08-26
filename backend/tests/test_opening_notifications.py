from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.time import pacific_today
from app.db.models import (
    Application,
    ApplicationParticipation,
    Base,
    Opening,
    OpeningOutcome,
)
from app.services.email_sender import CapturedEmailSender
from app.services.opening_notifications import send_due_unsuccessful_notices


class FailingEmailSender:
    def send(self, _message) -> str:
        raise RuntimeError("synthetic delivery failure")


def _db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)()


def _opening(db, *, archived: bool) -> Opening:
    today = pacific_today()
    opening = Opening(
        unit_size_bedrooms=2,
        housing_charge_cents=125_000,
        application_open_date=today - timedelta(days=30),
        application_close_date=today - timedelta(days=10),
        move_in_date=today if archived else today + timedelta(days=10),
        published_at=datetime.now(UTC),
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
        outcome_decided_at=datetime.now(UTC) if outcome is not None else None,
    )
    db.add(participation)
    db.commit()
    return participation


def test_notice_waits_until_every_active_opening_is_archived_and_final() -> None:
    db = _db()
    sender = CapturedEmailSender()
    application = _application(db, "applicant@example.com")
    archived = _opening(db, archived=True)
    closed = _opening(db, archived=False)
    first = _participate(db, application, archived, OpeningOutcome.UNSUCCESSFUL)
    second = _participate(db, application, closed, OpeningOutcome.UNSUCCESSFUL)

    assert send_due_unsuccessful_notices(db, sender) == 0

    closed.move_in_date = pacific_today()
    db.commit()
    assert send_due_unsuccessful_notices(db, sender) == 1
    assert len(sender.messages) == 1
    assert "your household was not selected" in sender.messages[0].text_body
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

    assert send_due_unsuccessful_notices(db, sender) == 0
    assert sender.messages == []


def test_accepted_notice_is_idempotent_if_marking_is_replayed() -> None:
    db = _db()
    sender = CapturedEmailSender()
    application = _application(db, "applicant@example.com")
    opening = _opening(db, archived=True)
    participation = _participate(
        db, application, opening, OpeningOutcome.UNSUCCESSFUL
    )

    assert send_due_unsuccessful_notices(db, sender) == 1
    participation.unsuccessful_notified_at = None
    db.commit()
    assert send_due_unsuccessful_notices(db, sender) == 1
    assert len(sender.messages) == 1
    assert participation.unsuccessful_notified_at is not None


def test_failed_notice_is_retried_without_marking_the_applicant_notified() -> None:
    db = _db()
    application = _application(db, "applicant@example.com")
    opening = _opening(db, archived=True)
    participation = _participate(
        db, application, opening, OpeningOutcome.UNSUCCESSFUL
    )

    assert send_due_unsuccessful_notices(db, FailingEmailSender()) == 0
    assert participation.unsuccessful_notified_at is None

    sender = CapturedEmailSender()
    assert send_due_unsuccessful_notices(db, sender) == 1
    assert len(sender.messages) == 1
    assert participation.unsuccessful_notified_at is not None
