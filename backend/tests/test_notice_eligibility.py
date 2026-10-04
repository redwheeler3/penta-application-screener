from datetime import UTC, datetime, timedelta

import pytest
from fastapi import Response
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.api.applicant.application import withdraw_applicant_application
from app.core.time import pacific_today
from app.db.models import (
    Application,
    ApplicationParticipation,
    EmailDelivery,
    EmailDeliveryState,
    MagicLinkToken,
    OpeningOutcome,
    VacancySubscription,
)
from app.schemas.openings import OpeningCreate
from app.services.email.outbox import email_queue_status, retry_queued_emails
from app.services.email.sender import CapturedEmailSender
from app.services.openings.catalog import create_opening
from app.services.openings.subscriptions import save_subscription
from app.services.openings.vacancy_notifications import (
    opening_audience,
    queue_opening_notifications,
)
from tests.db_support import memory_engine


def opening_values(today):
    return OpeningCreate.model_validate({"unitSizeBedrooms": 2, "housingChargeCents": 125000,
        "applicationCloseDate": today + timedelta(days=10), "moveInDate": today + timedelta(days=30)})


@pytest.mark.parametrize("change", ["withdrawn", "selected", "expired", "not_submitted"])
def test_notice_rechecks_a_recipient_changed_after_audience_capture(change):
    factory = sessionmaker(bind=memory_engine(foreign_keys=True), autoflush=False)
    today = pacific_today()
    with factory() as db:
        app = Application(primary_email="synthetic@example.com", raw_row={}, raw_row_hash="synthetic",
            normalized={}, submitted_at=datetime.now(UTC), retention_due_on=today + timedelta(days=100))
        db.add(app)
        db.commit()
        application_id = app.id
    with factory() as publisher:
        captured = opening_audience(publisher, 2)
        assert captured.total == 1
        with factory() as lifecycle:
            app = lifecycle.get(Application, application_id)
            if change == "withdrawn":
                withdraw_applicant_application(Response(), app, lifecycle)
            elif change == "selected":
                filled = create_opening(lifecycle, opening_values(today))
                lifecycle.add(ApplicationParticipation(application_id=app.id, opening_id=filled.id,
                    applied_at=datetime.now(UTC), outcome=OpeningOutcome.SELECTED))
            elif change == "expired":
                app.retention_due_on = today
            else:
                app.submitted_at = None
            lifecycle.commit()
        notice = create_opening(publisher, opening_values(today))
        queue_opening_notifications(publisher, notice, captured)
        publisher.commit()
    with factory() as worker:
        sender = CapturedEmailSender()
        assert retry_queued_emails(worker, sender).accepted == 0
        assert sender.messages == []
        delivery = worker.scalar(select(EmailDelivery))
        assert delivery.state == EmailDeliveryState.FAILED
        assert delivery.last_error_code == "ApplicationNoLongerNotifiable"
        assert delivery.magic_link_token_id is None
        assert worker.scalar(select(MagicLinkToken)) is None
        assert email_queue_status(worker).recent_failed == 0


@pytest.mark.parametrize("recipient", ["application", "subscription"])
@pytest.mark.parametrize("change", ["closed", "archived", "unpublished"])
def test_delayed_announcement_requires_an_open_published_opening(recipient, change):
    db = sessionmaker(bind=memory_engine(foreign_keys=True), autoflush=False)()
    today = pacific_today()
    if recipient == "application":
        db.add(Application(primary_email="synthetic@example.com", raw_row={}, raw_row_hash="synthetic",
            normalized={}, submitted_at=datetime.now(UTC), retention_due_on=today + timedelta(days=100)))
        db.commit()
    else:
        save_subscription(db, email="synthetic@example.com", unit_sizes={2}, source="synthetic")
    notice = create_opening(db, opening_values(today))
    queue_opening_notifications(db, notice, opening_audience(db, 2))
    db.commit()
    if change == "closed":
        notice.application_close_date = today - timedelta(days=1)
    elif change == "archived":
        notice.decided_at = datetime.now(UTC)
    else:
        notice.published_at = None
    db.commit()
    sender = CapturedEmailSender()
    assert retry_queued_emails(db, sender).accepted == 0
    assert sender.messages == []
    assert db.scalar(select(EmailDelivery)).last_error_code == "OpeningNoLongerOpen"
    assert db.scalar(select(MagicLinkToken)) is None
    assert email_queue_status(db).recent_failed == 0
    if recipient == "subscription":
        assert db.scalar(select(VacancySubscription)) is not None
    db.close()
