import pytest
from fastapi import BackgroundTasks
from sqlalchemy import event, func, select
from sqlalchemy.orm import sessionmaker

from app.api.applicant import application as routes
from app.core.problems import Problem
from app.db.models import (
    Application,
    ApplicationVersion,
    EmailDelivery,
    EmailDeliveryState,
)
from app.schemas.applicant.contracts import (
    SaveApplicationRequest,
    SubmitApplicationRequest,
)
from app.services.email.outbox import retry_queued_emails
from app.services.email.sender import CapturedEmailSender
from tests.applicant.support import sample_answers
from tests.application_support import current_opening_id
from tests.db_support import memory_engine


def setup():
    factory = sessionmaker(bind=memory_engine(foreign_keys=True), autoflush=False)
    with factory() as db:
        opening_id = current_opening_id(db)
        applicant = Application(primary_email="synthetic@example.com", raw_row={},
            raw_row_hash="synthetic", normalized={}, working_revision=1)
        db.add(applicant)
        db.commit()
        return factory, applicant.id, opening_id


def save_body(opening_id, revision, text):
    return SaveApplicationRequest.model_validate({"answers": sample_answers("synthetic@example.com", text),
        "openingIds": [opening_id], "baseRevision": revision})


def test_save_acknowledges_its_own_revision_after_another_tab_commits():
    factory, applicant_id, opening_id = setup()
    with factory() as first:
        @event.listens_for(first, "after_commit", once=True)
        def later_save(_db):
            with factory() as second:
                routes.save_applicant_application(save_body(opening_id, 2, "Newer draft"),
                    second, second.get(Application, applicant_id))

        acknowledged = routes.save_applicant_application(save_body(opening_id, 1, "Submitted snapshot"),
            first, first.get(Application, applicant_id))
        assert acknowledged.working_revision == 2
        assert acknowledged.answers.essays.household_introduction == "Submitted snapshot"
        with pytest.raises(Problem, match="saved in another"):
            routes.save_applicant_application(save_body(opening_id, acknowledged.working_revision, "Old tab edit"),
                first, first.get(Application, applicant_id))
    with factory() as observer:
        assert observer.get(Application, applicant_id).working_answers["essays"]["household_introduction"] == "Newer draft"


@pytest.mark.anyio
async def test_submission_commits_confirmation_before_delivery_and_keeps_its_acknowledgement():
    factory, applicant_id, opening_id = setup()
    tasks = BackgroundTasks()
    sender = CapturedEmailSender()
    body = SubmitApplicationRequest.model_validate({"answers": sample_answers("synthetic@example.com", "Published snapshot"),
        "openingIds": [opening_id], "baseRevision": 1, "declarationAccepted": True})

    def deliver(provider):
        with factory() as db:
            retry_queued_emails(db, provider)

    with factory() as db:
        acknowledged = routes.submit_applicant_application(body, tasks, db, sender,
            db.get(Application, applicant_id), deliver)
    assert sender.messages == []
    with factory() as observer:
        assert observer.scalar(select(EmailDelivery)).state == EmailDeliveryState.QUEUED
        routes.save_applicant_application(save_body(opening_id, 2, "Newer private draft"),
            observer, observer.get(Application, applicant_id))
    await tasks()
    assert len(sender.messages) == 1
    assert acknowledged.working_revision == 2
    assert acknowledged.answers.essays.household_introduction == "Published snapshot"


def test_confirmation_queue_failure_rolls_back_publication(monkeypatch):
    factory, applicant_id, opening_id = setup()

    def fail_queue(*_args):
        raise ValueError("Synthetic queue failure")

    monkeypatch.setattr(routes, "queue_submission_confirmation", fail_queue)
    body = SubmitApplicationRequest.model_validate({"answers": sample_answers("synthetic@example.com"),
        "openingIds": [opening_id], "baseRevision": 1, "declarationAccepted": True})
    with factory() as db:
        with pytest.raises(ValueError, match="Synthetic queue failure"):
            routes.submit_applicant_application(body, BackgroundTasks(), db, CapturedEmailSender(),
                db.get(Application, applicant_id), lambda _provider: None)
    with factory() as observer:
        assert observer.get(Application, applicant_id).working_revision == 1
        assert observer.scalar(select(func.count()).select_from(ApplicationVersion)) == 0
        assert observer.scalar(select(func.count()).select_from(EmailDelivery)) == 0


def test_withdrawing_from_every_opening_does_not_queue_a_submission_notice():
    factory, applicant_id, opening_id = setup()
    body = {"answers": sample_answers("synthetic@example.com"), "openingIds": [opening_id],
        "baseRevision": 1, "declarationAccepted": True}
    with factory() as db:
        routes.submit_applicant_application(SubmitApplicationRequest.model_validate(body), BackgroundTasks(), db,
            CapturedEmailSender(), db.get(Application, applicant_id), lambda _provider: None)
        body.update(openingIds=[], baseRevision=2)
        result = routes.submit_applicant_application(SubmitApplicationRequest.model_validate(body), BackgroundTasks(), db,
            CapturedEmailSender(), db.get(Application, applicant_id), lambda _provider: None)
        assert result.working_revision == 3
        assert all(not opening.participating for opening in result.openings)
        assert db.scalar(select(func.count()).select_from(EmailDelivery)) == 1
