import pytest
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import select

from app.db.models import (
    ApplicantDraft,
    Application,
    BrowserSession,
    EmailDelivery,
    EmailDeliveryState,
    MagicLinkPurpose,
    MagicLinkToken,
    PasswordlessIdentityKind,
)
from app.services.email.outbox import retry_queued_emails
from app.services.email.sender import (
    CapturedEmailSender,
    EmailQuotaExceededError,
    get_email_sender,
)
from tests.applicant.support import app_and_db, link_from_email, save_draft


class QuotaBlockedSender:
    def send(self, _message):
        raise EmailQuotaExceededError("Synthetic provider quota")


@pytest.mark.anyio
async def test_email_change_retries_keep_the_requested_address_and_session():
    app, db, initial = app_and_db()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        await save_draft(client)
        await client.post("/applicant/access-links/open", json={"token": link_from_email(initial), "switchCurrent": False})
        initiating_id = db.scalar(select(BrowserSession)).id
        app.dependency_overrides[get_email_sender] = QuotaBlockedSender
        request = await client.post("/applicant/application/email-change", json={"newEmail": "new-address@example.com"})
        assert request.json()["emailStatus"] == "failed"
        assert retry_queued_emails(db, QuotaBlockedSender()).accepted == 0
        delivered = CapturedEmailSender()
        assert retry_queued_emails(db, delivered).accepted == 1
        assert delivered.messages[0].to == ("new-address@example.com",)
        links = list(db.scalars(select(MagicLinkToken).where(MagicLinkToken.purpose == MagicLinkPurpose.EMAIL_CHANGE)))
        assert len(links) == 3
        assert all(link.email == "new-address@example.com" and link.initiating_session_id == initiating_id for link in links)
        app.dependency_overrides[get_email_sender] = lambda: initial
        confirmed = await client.post("/applicant/access-links/open",
            json={"token": link_from_email(delivered), "switchCurrent": False})
        assert confirmed.json()["state"] == "valid"
        assert db.scalar(select(Application)).primary_email == "new-address@example.com"


@pytest.mark.anyio
async def test_email_change_cannot_reissue_access_through_an_old_queued_guest_copy():
    from tests.applicant.support import sample_answers

    app, db, sender = app_and_db()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        await save_draft(client)
        await client.post("/applicant/access-links/open", json={"token": link_from_email(sender), "switchCurrent": False})
        app.dependency_overrides[get_email_sender] = QuotaBlockedSender
        checked = await client.post("/applicant/submissions/check", json={"answers": sample_answers(introduction="Other browser copy")})
        assert checked.json()["emailStatus"] == "failed"
        queued = db.scalar(select(EmailDelivery).where(EmailDelivery.state == EmailDeliveryState.QUEUED))
        assert queued.applicant_draft_id is not None
        app.dependency_overrides[get_email_sender] = lambda: sender
        await client.post("/applicant/application/email-change", json={"newEmail": "new-address@example.com"})
        confirmed = await client.post("/applicant/access-links/open", json={"token": link_from_email(sender), "switchCurrent": False})
        assert confirmed.json()["state"] == "valid"
    db.expire_all()
    assert db.get(ApplicantDraft, queued.applicant_draft_id).revoked_at is not None
    delivery = CapturedEmailSender()
    assert retry_queued_emails(db, delivery).accepted == 0
    assert delivery.messages == []
    db.refresh(queued)
    assert queued.state == EmailDeliveryState.FAILED
    assert queued.last_error_code == "ApplicantDraftUnavailable"


@pytest.mark.anyio
async def test_cancelling_email_change_discards_only_its_queued_confirmation():
    app, db, sender = app_and_db()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        await save_draft(client)
        await client.post("/applicant/access-links/open", json={"token": link_from_email(sender), "switchCurrent": False})
        app.dependency_overrides[get_email_sender] = QuotaBlockedSender
        await client.post("/applicant/application/email-change", json={"newEmail": "cancelled@example.com"})
        change = db.scalar(select(EmailDelivery).where(EmailDelivery.state == EmailDeliveryState.QUEUED))
        application_id = db.scalar(select(Application.id))
        other = EmailDelivery(application_id=application_id, message_kind="application_access",
            recipient_kind=PasswordlessIdentityKind.APPLICANT, state=EmailDeliveryState.QUEUED,
            retry_intent={"type": "magic_link", "purpose": "applicant_access"})
        db.add(other)
        db.commit()
        cancelled = await client.delete("/applicant/application/email-change")
        assert cancelled.status_code == 204
        db.refresh(change)
        db.refresh(other)
        assert change.state == EmailDeliveryState.FAILED
        assert change.last_error_code == "EmailChangeCancelled"
        assert change.retry_intent is None
        assert other.state == EmailDeliveryState.QUEUED
        delivered = CapturedEmailSender()
        assert retry_queued_emails(db, delivered).accepted == 1
        assert delivered.messages[0].to == ("avery@example.com",)


@pytest.mark.anyio
async def test_verified_email_change_updates_identity_and_private_answers() -> None:
    app, db, sender = app_and_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await save_draft(client)
        await client.post(
            "/applicant/access-links/open",
            json={"token": link_from_email(sender), "switchCurrent": False},
        )
        application = db.scalar(select(Application))
        assert application is not None
        application.google_subject = "linked-google-subject"
        db.commit()
        requested = await client.post(
            "/applicant/application/email-change",
            json={"newEmail": "new-address@example.com"},
        )
        token = link_from_email(sender)
        inspected = await client.post(
            "/applicant/access-links/inspect", json={"token": token}
        )
        opened = await client.post(
            "/applicant/access-links/open",
            json={"token": token, "switchCurrent": False, "rememberDevice": True},
        )
        stored = await client.get("/applicant/application")

    application = db.scalar(select(Application))
    assert application is not None
    assert requested.status_code == 202
    assert inspected.json()["purpose"] == "email_change"
    assert inspected.json()["switchRequired"] is False
    assert inspected.json()["applicationEmail"] == "avery@example.com"
    assert opened.json()["state"] == "valid"
    assert opened.json()["googleDisconnected"] is True
    assert stored.json()["primaryEmail"] == "new-address@example.com"
    assert stored.json()["answers"]["applicant"]["email"] == "new-address@example.com"
    assert application.raw_row == {}
    assert application.google_subject is None
    assert sender.messages[-2].kind == "application_email_change_confirmation"
    assert sender.messages[-2].to == ("new-address@example.com",)
    assert "will not change unless you confirm it" in sender.messages[-2].text_body
    assert sender.messages[-1].kind == "application_email_changed"
    assert sender.messages[-1].to == ("avery@example.com",)
    assert "If you made this change, no action is needed" in sender.messages[-1].text_body
    assert "techsupport@pentacoop.com" in sender.messages[-1].text_body
    assert "new-address@example.com" in sender.messages[-1].text_body
    assert "new-address@example.com" in sender.messages[-1].html_body
    assert "{{HsUnsubscribe}}" in sender.messages[-1].text_body
    assert (
        "<HsUnsubscribe>Click here to permanently unsubscribe.</HsUnsubscribe>"
        in sender.messages[-1].html_body
    )
    assert "Privacy questions" not in sender.messages[-1].html_body
    assert (
        'not monitored.</span><br><span style="display:inline-block;margin-top:8px;">'
        "Sent by" in sender.messages[-1].html_body
    )
    assert "Penta Tech Support" in sender.messages[-1].text_body
    active_sessions = list(
        db.scalars(select(BrowserSession).where(BrowserSession.revoked_at.is_(None)))
    )
    assert len(active_sessions) == 2


@pytest.mark.anyio
async def test_email_change_never_merges_with_an_existing_application() -> None:
    app, db, sender = app_and_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await save_draft(client)
        await client.post(
            "/applicant/access-links/open",
            json={"token": link_from_email(sender), "switchCurrent": False},
        )
        original = db.scalar(select(Application))
        assert original is not None
        db.add(
            Application(
                primary_email="already-used@example.com",
                applicant_name="Other Applicant",
                raw_row={},
                raw_row_hash="other",
                normalized={},
            )
        )
        db.commit()
        await client.post(
            "/applicant/application/email-change",
            json={"newEmail": "already-used@example.com"},
        )
        opened = await client.post(
            "/applicant/access-links/open",
            json={"token": link_from_email(sender), "switchCurrent": False},
        )

    db.refresh(original)
    assert opened.json()["state"] == "email_in_use"
    assert original.primary_email == "avery@example.com"
    assert len(sender.messages) == 2


@pytest.mark.anyio
async def test_different_email_change_requests_coexist_until_one_is_confirmed() -> None:
    app, db, sender = app_and_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await save_draft(client)
        await client.post(
            "/applicant/access-links/open",
            json={"token": link_from_email(sender), "switchCurrent": False},
        )
        first = await client.post(
            "/applicant/application/email-change",
            json={"newEmail": "first-new@example.com"},
        )
        second = await client.post(
            "/applicant/application/email-change",
            json={"newEmail": "second-new@example.com"},
        )
        stored = await client.get("/applicant/application")

    links = list(
        db.scalars(
            select(MagicLinkToken)
            .where(MagicLinkToken.purpose == MagicLinkPurpose.EMAIL_CHANGE)
            .order_by(MagicLinkToken.created_at)
        )
    )
    assert first.json()["emailSent"] is True
    assert second.json()["emailSent"] is True
    assert len(links) == 2
    assert links[0].revoked_at is None
    assert links[1].revoked_at is None
    assert stored.json()["pendingEmailChange"] == "second-new@example.com"
