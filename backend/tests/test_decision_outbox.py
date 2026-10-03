"""Permanent decisions and outcome intents commit together before provider I/O."""

import pytest
from fastapi import BackgroundTasks
from sqlalchemy import select

from app.api.openings import select_no_household
from app.db.models import (
    ApplicationParticipation,
    EmailDelivery,
    EmailDeliveryState,
    Opening,
    User,
)
from app.services.email.outbox import retry_queued_emails
from app.services.email.sender import CapturedEmailSender
from app.services.openings import selection
from tests.test_write_concurrency import request_sessions


def test_decision_is_acknowledged_with_durable_intents_before_delivery() -> None:
    factory, opening_id, admin_id, _ids = request_sessions(closed=True)
    sender = CapturedEmailSender()
    tasks = BackgroundTasks()

    def drain(active_sender):
        with factory() as db:
            retry_queued_emails(db, active_sender)

    with factory() as db:
        response = select_no_household(opening_id, tasks, admin=db.get(User, admin_id), db=db, sender=sender, outbox_runner=drain)
        assert response.queued_notification_count == 2
        assert sender.messages == []
    with factory() as db:
        assert db.get(Opening, opening_id).no_household_selected is True
        assert [row.state for row in db.scalars(select(EmailDelivery))] == [EmailDeliveryState.QUEUED] * 2
        assert all(row.unsuccessful_notified_at is None for row in db.scalars(select(ApplicationParticipation)))
    task = tasks.tasks[0]
    task.func(*task.args, **task.kwargs)
    assert len(sender.messages) == 2
    with factory() as db:
        assert all(row.unsuccessful_notified_at is not None for row in db.scalars(select(ApplicationParticipation)))


def test_queue_failure_cannot_commit_an_opening_decision_without_its_intents(monkeypatch) -> None:
    factory, opening_id, admin_id, _ids = request_sessions(closed=True)

    def fail_queue(*_args, **_kwargs):
        raise RuntimeError("Synthetic staging failure")

    monkeypatch.setattr(selection, "queue_due_unsuccessful_notices", fail_queue)
    with factory() as db:
        with pytest.raises(RuntimeError, match="Synthetic staging failure"):
            selection.confirm_no_household_selected(db, db.get(Opening, opening_id), decided_by=db.get(User, admin_id))
        db.rollback()
    with factory() as db:
        assert db.get(Opening, opening_id).decided_at is None
        assert all(row.outcome is None for row in db.scalars(select(ApplicationParticipation)))
        assert db.scalar(select(EmailDelivery)) is None
