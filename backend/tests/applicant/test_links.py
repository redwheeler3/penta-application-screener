from datetime import UTC, datetime, timedelta

import pytest
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.core.time import as_utc, pacific_today
from app.db.models import (
    ApplicantDraft,
    Application,
    ApplicationParticipation,
    BrowserSession,
    MagicLinkPurpose,
    MagicLinkToken,
    Opening,
    OpeningOutcome,
    PasswordlessIdentityKind,
)
from app.schemas.applicant.answers import WorkingApplicationAnswers
from app.services.intake import save_working_copy
from app.services.passwordless_auth import issue_magic_link
from tests.applicant.support import (
    app_and_db,
    link_from_email,
    sample_answers,
    save_draft,
)


@pytest.mark.anyio
async def test_pending_draft_cannot_be_reopened_after_applications_archive() -> None:
    app, db, sender = app_and_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await save_draft(client)
        token = link_from_email(sender)
        opening = db.scalar(select(Opening))
        assert opening is not None
        opening.application_close_date = pacific_today() - timedelta(days=2)
        opening.move_in_date = pacific_today() - timedelta(days=1)
        db.commit()
        sender.messages.clear()

        requested = await client.post(
            "/applicant/access-links/request",
            json={"answers": sample_answers()},
        )
        inspected = await client.post(
            "/applicant/access-links/inspect",
            json={"token": token},
        )
        regenerated = await client.post(
            "/applicant/access-links/regenerate",
            json={"token": token},
        )

    assert requested.json()["emailStatus"] == "sent"
    assert inspected.json()["state"] == "unavailable"
    assert regenerated.json()["emailStatus"] == "sent"
    assert len(sender.messages) == 1
    assert sender.messages[0].kind == "application_unavailable"


@pytest.mark.anyio
async def test_email_change_link_cannot_mutate_a_selected_application() -> None:
    app, db, _sender = app_and_db()
    opening = db.scalar(select(Opening))
    assert opening is not None
    application = Application(
        primary_email="avery@example.com",
        raw_row=sample_answers(),
        raw_row_hash="selected",
        normalized={},
        working_answers=sample_answers(),
        working_content_hash="selected",
        working_saved_at=datetime.now(UTC),
        submitted_at=datetime.now(UTC),
    )
    db.add(application)
    db.flush()
    db.add(
        ApplicationParticipation(
            application_id=application.id,
            opening_id=opening.id,
            applied_at=datetime.now(UTC),
            outcome=OpeningOutcome.SELECTED,
        )
    )
    issued = issue_magic_link(
        db,
        identity_kind=PasswordlessIdentityKind.APPLICANT,
        email="new-address@example.com",
        purpose=MagicLinkPurpose.EMAIL_CHANGE,
        application_id=application.id,
    )
    db.commit()
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        inspected = await client.post(
            "/applicant/access-links/inspect", json={"token": issued.token}
        )
        opened = await client.post(
            "/applicant/access-links/open",
            json={"token": issued.token, "switchCurrent": False},
        )

    db.refresh(application)
    assert inspected.json()["state"] == "unavailable"
    assert opened.json()["state"] == "unavailable"
    assert application.primary_email == "avery@example.com"
    assert application.working_answers["applicant"]["email"] == "avery@example.com"
    assert db.scalar(select(func.count()).select_from(BrowserSession)) == 0
    assert len(list(db.scalars(select(MagicLinkToken)))) == 1


@pytest.mark.anyio
async def test_application_link_cannot_start_a_session_after_openings_archive() -> None:
    app, db, sender = app_and_db()
    opening = db.scalar(select(Opening))
    assert opening is not None
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        submitted = await client.post(
            "/applicant/submissions",
            json={
                "answers": sample_answers(),
                "openingIds": [opening.id],
                "declarationAccepted": True,
            },
        )
        assert submitted.status_code == 201
        token = link_from_email(sender)
        opening.application_close_date = pacific_today() - timedelta(days=2)
        opening.move_in_date = pacific_today() - timedelta(days=1)
        db.commit()

        inspected = await client.post(
            "/applicant/access-links/inspect",
            json={"token": token},
        )
        opened = await client.post(
            "/applicant/access-links/open",
            json={"token": token, "switchCurrent": False},
        )

    assert inspected.json()["state"] == "unavailable"
    assert opened.json()["state"] == "unavailable"
    assert opened.json()["applicationId"] is None


@pytest.mark.anyio
async def test_authenticated_return_link_saves_current_answers_before_emailing() -> None:
    app, db, sender = app_and_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await save_draft(client)
        await client.post(
            "/applicant/access-links/open",
            json={"token": link_from_email(sender), "switchCurrent": False},
        )
        original_link = db.scalar(select(MagicLinkToken))
        assert original_link is not None
        original_link.created_at = datetime.now(UTC) - timedelta(minutes=10)
        db.commit()
        sender.messages.clear()
        restored = await client.get("/applicant/application")
        response = await client.post(
            "/applicant/access-links/request",
            json={
                "answers": sample_answers(introduction="Authenticated saved answers"),
                "baseRevision": restored.json()["workingRevision"],
            },
        )

    application = db.scalar(select(Application))
    assert application is not None
    assert response.status_code == 202
    assert response.json() == {
        "accepted": True,
        "currentAnswersSaved": True,
        "emailStatus": "sent",
    }
    assert application.working_answers["essays"]["household_introduction"] == (
        "Authenticated saved answers"
    )
    assert len(sender.messages) == 1


@pytest.mark.anyio
async def test_valid_link_claims_draft_without_submitting_and_uses_session_cookie_by_default() -> None:
    app, db, sender = app_and_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await save_draft(client, intent="submit")
        token = link_from_email(sender)
        opened = await client.post(
            "/applicant/access-links/open",
            json={"token": token, "switchCurrent": False},
        )
        stored = await client.get("/applicant/application")

    assert opened.status_code == 200
    assert opened.json()["pendingIntent"] == "submit"
    assert "Max-Age" not in opened.headers["set-cookie"]
    assert stored.json()["answers"]["essays"]["householdIntroduction"] == "Synthetic introduction"
    assert db.scalar(select(ApplicationParticipation)) is None


@pytest.mark.anyio
async def test_remembered_device_receives_persistent_cookie() -> None:
    app, _db, sender = app_and_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await save_draft(client)
        opened = await client.post(
            "/applicant/access-links/open",
            json={"token": link_from_email(sender), "switchCurrent": False, "rememberDevice": True},
        )

    assert "Max-Age=" in opened.headers["set-cookie"]


@pytest.mark.anyio
async def test_expired_link_can_send_a_replacement_without_retyping_email() -> None:
    app, db, sender = app_and_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await save_draft(client)
        token = link_from_email(sender)
        original = db.scalar(select(MagicLinkToken))
        assert original is not None
        original.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        original.created_at = datetime.now(UTC) - timedelta(minutes=1)
        db.commit()
        inspected = await client.post("/applicant/access-links/inspect", json={"token": token})
        regenerated = await client.post(
            "/applicant/access-links/regenerate",
            json={"token": token},
        )

    assert inspected.json()["state"] == "expired"
    assert regenerated.status_code == 202
    assert regenerated.json()["emailSent"] is True
    assert len(sender.messages) == 2
    assert link_from_email(sender) != token


@pytest.mark.anyio
async def test_different_active_applicant_must_confirm_before_link_is_consumed() -> None:
    app, db, sender = app_and_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await save_draft(client, email="first@example.com")
        first_token = link_from_email(sender)
        await client.post(
            "/applicant/access-links/open",
            json={"token": first_token, "switchCurrent": False},
        )
        await save_draft(client, email="second@example.com")
        second_token = link_from_email(sender)
        inspected = await client.post(
            "/applicant/access-links/inspect", json={"token": second_token}
        )
        not_switched = await client.post(
            "/applicant/access-links/open",
            json={"token": second_token, "switchCurrent": False},
        )
        link = db.scalar(select(MagicLinkToken).where(MagicLinkToken.email == "second@example.com"))
        assert link is not None
        assert link.consumed_at is None
        switched = await client.post(
            "/applicant/access-links/open",
            json={"token": second_token, "switchCurrent": True},
        )

    assert inspected.json()["switchRequired"] is True
    assert inspected.json()["currentEmail"] == "first@example.com"
    assert inspected.json()["linkEmail"] == "second@example.com"
    assert not_switched.json()["switchRequired"] is True
    assert switched.json()["currentEmail"] == "second@example.com"
    active_sessions = list(db.scalars(select(BrowserSession).order_by(BrowserSession.id)))
    assert active_sessions[0].revoked_at is not None


@pytest.mark.anyio
async def test_stale_link_for_another_applicant_offers_resend_without_switching() -> None:
    app, db, sender = app_and_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await save_draft(client, email="first@example.com")
        await client.post(
            "/applicant/access-links/open",
            json={"token": link_from_email(sender), "switchCurrent": False},
        )
        await save_draft(client, email="second@example.com")
        second_token = link_from_email(sender)
        second_link = db.scalar(
            select(MagicLinkToken).where(MagicLinkToken.email == "second@example.com")
        )
        assert second_link is not None
        second_link.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        second_link.created_at = datetime.now(UTC) - timedelta(minutes=1)
        db.commit()
        inspected = await client.post(
            "/applicant/access-links/inspect", json={"token": second_token}
        )
        regenerated = await client.post(
            "/applicant/access-links/regenerate",
            json={"token": second_token},
        )
        current = await client.get("/applicant/application")

    assert inspected.json()["state"] == "expired"
    assert inspected.json()["switchRequired"] is True
    assert regenerated.json()["emailSent"] is True
    assert current.json()["answers"]["applicant"]["email"] == "first@example.com"


@pytest.mark.anyio
@pytest.mark.parametrize("choice", ["saved", "guest"])
async def test_claim_asks_owner_which_private_copy_to_keep(choice: str) -> None:
    app, db, sender = app_and_db()
    existing = Application(
        primary_email="avery@example.com",
        applicant_name="Existing Applicant",
        raw_row={"submitted": "unchanged"},
        raw_row_hash="existing-hash",
        normalized={"applicant_name": "Existing Applicant"},
        submitted_at=datetime.now(UTC),
    )
    db.add(existing)
    db.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await save_draft(client)
        draft = db.scalar(select(ApplicantDraft))
        assert draft is not None
        save_working_copy(
            existing,
            WorkingApplicationAnswers.model_validate(
                sample_answers(introduction="Existing working answers")
            ),
            saved_at=as_utc(draft.saved_at) + timedelta(minutes=1),
        )
        db.commit()
        opened = await client.post(
            "/applicant/access-links/open",
            json={"token": link_from_email(sender), "switchCurrent": False},
        )
        pending = await client.get("/applicant/application/pending-copy")
        reconciled = await client.post(
            "/applicant/application/pending-copy", json={"choice": choice}
        )
        stored = await client.get("/applicant/application")

    db.refresh(existing)
    db.refresh(draft)
    assert opened.status_code == 200
    assert opened.json()["pendingCopy"]["guestAnswers"]["essays"]["householdIntroduction"] == "Synthetic introduction"
    assert pending.json()["pendingCopy"] == opened.json()["pendingCopy"]
    assert reconciled.status_code == 204
    assert stored.json()["answers"]["essays"]["householdIntroduction"] == (
        "Synthetic introduction" if choice == "guest" else "Existing working answers"
    )
    assert existing.raw_row == {"submitted": "unchanged"}
    assert draft.resolved_at is not None
    session = db.scalar(select(BrowserSession))
    assert session is not None
    assert session.reconciliation_draft_id is None


@pytest.mark.anyio
async def test_draft_past_its_opening_retention_date_cannot_be_opened_or_regenerated() -> None:
    app, db, sender = app_and_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await save_draft(client)
        token = link_from_email(sender)
        draft = db.scalar(select(ApplicantDraft))
        assert draft is not None
        draft.retention_due_on = pacific_today() - timedelta(days=1)
        db.commit()
        inspected = await client.post("/applicant/access-links/inspect", json={"token": token})
        regenerated = await client.post(
            "/applicant/access-links/regenerate",
            json={"token": token},
        )

    assert inspected.json()["state"] == "abandoned"
    assert regenerated.json()["emailSent"] is False
    assert len(sender.messages) == 1
