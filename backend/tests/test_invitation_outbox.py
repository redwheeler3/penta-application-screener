import pytest
from fastapi import BackgroundTasks
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.api.allowlist import upsert_allowlist_entry
from app.db.models import (
    AccessAllowlistEntry,
    EmailDelivery,
    EmailDeliveryState,
    User,
    UserRole,
)
from app.schemas.allowlist import AllowlistUpsert
from app.services.email.outbox import retry_queued_emails
from app.services.email.sender import CapturedEmailSender
from tests.db_support import memory_engine


@pytest.mark.anyio
async def test_invitation_response_precedes_provider_work_and_commits_the_intent() -> None:
    factory = sessionmaker(bind=memory_engine(foreign_keys=True), autoflush=False)
    sender = CapturedEmailSender()
    background = BackgroundTasks()

    def run_outbox(provider):
        with factory() as db:
            retry_queued_emails(db, provider)

    with factory() as db:
        admin = User(email="admin@example.com", display_name="Synthetic Admin", role=UserRole.ADMIN)
        db.add(admin)
        db.commit()
        response = upsert_allowlist_entry(AllowlistUpsert(email="invited@example.com"),
            background, admin, db, sender, run_outbox)
        assert response.invitation_email_status == "queued"
        assert sender.messages == []
    with factory() as observer:
        assert observer.scalar(select(AccessAllowlistEntry)) is not None
        delivery = observer.scalar(select(EmailDelivery))
        assert delivery.state == EmailDeliveryState.QUEUED
        assert delivery.user_id is not None
        assert delivery.recipient_email is None
        assert delivery.magic_link_token_id is None
    await background()
    assert len(sender.messages) == 1
    assert sender.messages[0].kind == "committee_invitation"
    with factory() as observer:
        assert observer.scalar(select(EmailDelivery)).state == EmailDeliveryState.ACCEPTED


def test_queue_failure_does_not_leave_access_without_its_invitation(monkeypatch) -> None:
    from app.api import allowlist

    factory = sessionmaker(bind=memory_engine(foreign_keys=True), autoflush=False)

    def fail_queue(*_args):
        raise ValueError("Synthetic queue failure")

    monkeypatch.setattr(allowlist, "queue_committee_invitation", fail_queue)
    with factory() as db:
        admin = User(email="admin@example.com", display_name="Synthetic Admin", role=UserRole.ADMIN)
        db.add(admin)
        db.commit()
        with pytest.raises(ValueError, match="Synthetic queue failure"):
            upsert_allowlist_entry(AllowlistUpsert(email="invited@example.com"), BackgroundTasks(),
                admin, db, CapturedEmailSender(), lambda _sender: None)
    with factory() as observer:
        assert observer.scalar(select(AccessAllowlistEntry)) is None
        assert observer.scalar(select(User).where(User.email == "invited@example.com")) is None
        assert observer.scalar(select(EmailDelivery)) is None
