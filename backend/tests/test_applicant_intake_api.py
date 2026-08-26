import re
from datetime import UTC, date, datetime, timedelta

import pytest
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.time import as_utc, pacific_today
from app.db.models import (
    ApplicantDraft,
    Application,
    ApplicationParticipation,
    ApplicationVersion,
    Base,
    BrowserSession,
    MagicLinkPurpose,
    MagicLinkToken,
    Opening,
)
from app.db.session import get_db
from app.main import create_app
from app.schemas.intake import WorkingApplicationAnswers
from app.services.email_sender import CapturedEmailSender, get_email_sender
from app.services.intake import save_working_copy


class FailingEmailSender:
    def send(self, _message) -> str:
        raise TimeoutError("synthetic provider timeout")


def _app_and_db() -> tuple:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    test_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = test_session()
    today = date.today()
    db.add(
        Opening(
            unit_size_bedrooms=2,
            housing_charge_cents=100_000,
            application_open_date=today - timedelta(days=1),
            application_close_date=today + timedelta(days=10),
            move_in_date=today + timedelta(days=30),
            published_at=datetime.now(UTC),
        )
    )
    db.commit()
    app = create_app()
    sender = CapturedEmailSender()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_email_sender] = lambda: sender
    return app, db, sender


def _answers(email: str = "avery@example.com", introduction: str = "Synthetic introduction") -> dict:
    reference = {
        "name": "Synthetic Reference",
        "email": "reference@example.com",
        "phone": "(604) 555-0101",
    }
    return {
        "applicant": {
            "firstName": "Avery",
            "lastName": "Ng",
            "birthDate": "1990-04-12",
            "phone": "(604) 555-0102",
            "email": email,
        },
        "coApplicant": None,
        "children": [],
        "currentAddress": {
            "street": "123 Synthetic Street",
            "street2": None,
            "city": "Vancouver",
            "provinceOrState": "BC",
            "postalOrZipCode": "V6R 1A1",
            "country": "Canada",
        },
        "livedAtCurrentAddressTwoYears": True,
        "ownsCurrentHome": False,
        "ownsOtherRealEstate": False,
        "currentLandlord": reference,
        "previousLandlord": None,
        "essays": {
            "householdIntroduction": introduction,
            "skillsToContribute": "Synthetic maintenance and organizing skills.",
            "previousCoopExperience": "No previous co-op experience.",
            "whyCoop": "Synthetic interest in community living.",
            "additionalInformation": "Synthetic additional context.",
        },
        "pets": None,
        "householdPhotoLink": "https://example.com/synthetic-household-photo",
        "applicantEmployment": {
            "status": "employed",
            "jobTitle": "Synthetic role",
            "companyName": "Synthetic employer",
            "startDate": "2020-01-02",
            "manager": reference,
        },
        "coApplicantEmployment": None,
        "applicantIncome": 80000,
        "coApplicantIncome": None,
    }


def _link(sender: CapturedEmailSender) -> str:
    match = re.search(r"#applicant-link=([^\s]+)", sender.messages[-1].text_body)
    assert match is not None
    return match.group(1)


async def _save_draft(client: AsyncClient, *, email: str = "avery@example.com", intent: str = "save"):
    return await client.post(
        "/applicant/drafts",
        json={"answers": _answers(email), "intent": intent},
    )


@pytest.mark.anyio
async def test_save_immediately_persists_private_draft_and_sends_access_link() -> None:
    app, db, _sender = _app_and_db()
    transport = ASGITransport(app=app)
    before = datetime.now(UTC)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await _save_draft(client)

    assert response.status_code == 202
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["emailSent"] is True
    assert db.scalar(select(Application)) is None
    draft = db.scalar(select(ApplicantDraft))
    link = db.scalar(select(MagicLinkToken))
    assert draft is not None
    assert link is not None
    assert draft.working_answers["essays"]["household_introduction"] == "Synthetic introduction"
    assert draft.working_answers["household_photo_link"] == "https://example.com/synthetic-household-photo"
    assert link.applicant_draft_id == draft.id
    assert timedelta(hours=23, minutes=59) < link.expires_at.replace(tzinfo=UTC) - before <= timedelta(hours=24, seconds=5)


@pytest.mark.anyio
async def test_delivery_failure_never_discards_the_saved_pending_draft() -> None:
    app, db, _sender = _app_and_db()
    app.dependency_overrides[get_email_sender] = lambda: FailingEmailSender()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await _save_draft(client)

    draft = db.scalar(select(ApplicantDraft))
    assert response.status_code == 202
    assert response.json()["emailSent"] is False
    assert draft is not None
    assert draft.revoked_at is None
    assert draft.working_answers is not None


@pytest.mark.anyio
async def test_delivery_failure_does_not_suppress_an_immediate_retry() -> None:
    app, db, _sender = _app_and_db()
    app.dependency_overrides[get_email_sender] = lambda: FailingEmailSender()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        opening = db.scalar(select(Opening))
        assert opening is not None
        request = {"answers": _answers(), "openingIds": [opening.id]}
        first = await client.post("/applicant/access-links/request", json=request)
        second = await client.post("/applicant/access-links/request", json=request)

    assert first.json()["emailStatus"] == "failed"
    assert second.json()["emailStatus"] == "failed"
    assert len(list(db.scalars(select(MagicLinkToken)))) == 2


@pytest.mark.anyio
async def test_save_and_return_later_accepts_an_incomplete_application() -> None:
    app, db, sender = _app_and_db()
    answers = _answers()
    answers["applicant"]["firstName"] = ""
    answers["applicant"]["birthDate"] = "1974-"
    answers["essays"] = {
        "householdIntroduction": "",
        "skillsToContribute": "",
        "previousCoopExperience": "",
        "whyCoop": "",
        "additionalInformation": "",
    }
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/applicant/drafts",
            json={"answers": answers, "intent": "save"},
        )

    assert response.status_code == 202
    assert db.scalar(select(ApplicantDraft)) is not None
    assert len(sender.messages) == 1


@pytest.mark.anyio
async def test_guest_can_submit_directly_and_receives_application_access() -> None:
    app, db, sender = _app_and_db()
    opening = db.scalar(select(Opening))
    assert opening is not None
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/applicant/submissions",
            json={
                "answers": _answers(),
                "openingIds": [opening.id],
                "declarationAccepted": True,
            },
        )

    application = db.scalar(select(Application))
    assert response.status_code == 201
    assert response.json() == {
        "submitted": True,
        "emailSent": True,
        "emailStatus": "sent",
    }
    assert application is not None
    assert application.submitted_at is not None
    assert db.scalar(select(ApplicationVersion.application_id)) == application.id
    assert db.scalar(select(ApplicationParticipation.opening_id)) == opening.id
    assert len(sender.messages) == 1


@pytest.mark.anyio
async def test_guest_with_existing_email_is_stopped_before_review_and_sent_access() -> None:
    app, _db, sender = _app_and_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await _save_draft(client)
        await client.post(
            "/applicant/access-links/open",
            json={"token": _link(sender), "switchCurrent": False},
        )
        await client.post("/applicant/auth/logout")
        response = await client.post(
            "/applicant/submissions/check",
            json={"email": "avery@example.com"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "canSubmit": False,
        "emailSent": True,
        "emailStatus": "sent",
    }
    assert len(sender.messages) == 2


@pytest.mark.anyio
async def test_return_link_request_does_not_reveal_whether_application_exists() -> None:
    app, db, sender = _app_and_db()
    existing_application = Application(
        primary_email="returning@example.com",
        applicant_name="Synthetic Returning Applicant",
        raw_row={"submitted": "unchanged"},
        raw_row_hash="returning",
        normalized={},
    )
    db.add(existing_application)
    db.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        existing = await client.post(
            "/applicant/access-links/request",
            json={"answers": _answers("returning@example.com", "Ignored browser answers")},
        )
        missing = await client.post(
            "/applicant/access-links/request",
            json={"answers": _answers("missing@example.com", "New saved draft")},
        )

    assert existing.status_code == missing.status_code == 202
    assert existing.json() == missing.json() == {
        "accepted": True,
        "currentAnswersSaved": False,
        "emailStatus": "sent",
    }
    assert "emailSent" not in existing.json() | missing.json()
    assert existing_application.working_answers is None
    drafts = list(db.scalars(select(ApplicantDraft)))
    assert len(drafts) == 1
    assert drafts[0].email == "missing@example.com"
    assert drafts[0].working_answers["essays"]["household_introduction"] == "New saved draft"
    assert len(sender.messages) == 2
    assert sender.messages[0].to == ("returning@example.com",)
    assert sender.messages[1].to == ("missing@example.com",)


@pytest.mark.anyio
async def test_return_link_request_finds_an_unclaimed_pending_draft() -> None:
    app, db, sender = _app_and_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await _save_draft(client)
        original_link = db.scalar(select(MagicLinkToken))
        assert original_link is not None
        original_link.created_at = datetime.now(UTC) - timedelta(minutes=10)
        db.commit()
        sender.messages.clear()

        response = await client.post(
            "/applicant/access-links/request",
            json={"answers": _answers(introduction="Ignored replacement")},
        )

    links = list(db.scalars(select(MagicLinkToken).order_by(MagicLinkToken.id)))
    drafts = list(db.scalars(select(ApplicantDraft)))
    assert response.status_code == 202
    assert len(sender.messages) == 1
    assert len(drafts) == 1
    assert drafts[0].working_answers["essays"]["household_introduction"] == "Synthetic introduction"
    assert len(links) == 2
    assert links[-1].applicant_draft_id is not None


@pytest.mark.anyio
async def test_authenticated_return_link_saves_current_answers_before_emailing() -> None:
    app, db, sender = _app_and_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await _save_draft(client)
        await client.post(
            "/applicant/access-links/open",
            json={"token": _link(sender), "switchCurrent": False},
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
                "answers": _answers(introduction="Authenticated saved answers"),
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
    app, db, sender = _app_and_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await _save_draft(client, intent="submit")
        token = _link(sender)
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
    app, _db, sender = _app_and_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await _save_draft(client)
        opened = await client.post(
            "/applicant/access-links/open",
            json={"token": _link(sender), "switchCurrent": False, "rememberDevice": True},
        )

    assert "Max-Age=" in opened.headers["set-cookie"]


@pytest.mark.anyio
async def test_verified_email_change_updates_identity_and_private_answers() -> None:
    app, db, sender = _app_and_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await _save_draft(client)
        await client.post(
            "/applicant/access-links/open",
            json={"token": _link(sender), "switchCurrent": False},
        )
        requested = await client.post(
            "/applicant/application/email-change",
            json={"newEmail": "new-address@example.com"},
        )
        token = _link(sender)
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
    assert stored.json()["primaryEmail"] == "new-address@example.com"
    assert stored.json()["answers"]["applicant"]["email"] == "new-address@example.com"
    assert application.raw_row == {}
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
    assert "<a href=" not in sender.messages[-1].html_body
    assert "Penta Tech Support" in sender.messages[-1].text_body
    active_sessions = list(
        db.scalars(select(BrowserSession).where(BrowserSession.revoked_at.is_(None)))
    )
    assert len(active_sessions) == 2


@pytest.mark.anyio
async def test_email_change_never_merges_with_an_existing_application() -> None:
    app, db, sender = _app_and_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await _save_draft(client)
        await client.post(
            "/applicant/access-links/open",
            json={"token": _link(sender), "switchCurrent": False},
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
            json={"token": _link(sender), "switchCurrent": False},
        )

    db.refresh(original)
    assert opened.json()["state"] == "email_in_use"
    assert original.primary_email == "avery@example.com"
    assert len(sender.messages) == 2


@pytest.mark.anyio
async def test_email_change_requires_recent_authentication() -> None:
    app, db, sender = _app_and_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await _save_draft(client)
        await client.post(
            "/applicant/access-links/open",
            json={"token": _link(sender), "switchCurrent": False},
        )
        session = db.scalar(
            select(BrowserSession).where(BrowserSession.revoked_at.is_(None))
        )
        assert session is not None
        session.recently_authenticated_at = datetime.now(UTC) - timedelta(days=2)
        db.commit()
        response = await client.post(
            "/applicant/application/email-change",
            json={"newEmail": "new-address@example.com"},
        )
        reauthentication = await client.post("/applicant/application/reauthentication")

    assert response.status_code == 401
    assert response.json()["code"] == "recent_authentication_required"
    links = db.scalars(
        select(MagicLinkToken).where(MagicLinkToken.purpose == MagicLinkPurpose.EMAIL_CHANGE)
    ).all()
    assert not links
    assert reauthentication.status_code == 202
    assert reauthentication.json()["emailSent"] is True
    assert sender.messages[-1].to == ("avery@example.com",)


@pytest.mark.anyio
async def test_different_email_change_request_immediately_replaces_the_first() -> None:
    app, db, sender = _app_and_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await _save_draft(client)
        await client.post(
            "/applicant/access-links/open",
            json={"token": _link(sender), "switchCurrent": False},
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
    assert links[0].revoked_at is not None
    assert links[1].revoked_at is None
    assert stored.json()["pendingEmailChange"] == "second-new@example.com"


@pytest.mark.anyio
async def test_expired_link_can_send_a_replacement_without_retyping_email() -> None:
    app, db, sender = _app_and_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await _save_draft(client)
        token = _link(sender)
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
    assert _link(sender) != token


@pytest.mark.anyio
async def test_different_active_applicant_must_confirm_before_link_is_consumed() -> None:
    app, db, sender = _app_and_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await _save_draft(client, email="first@example.com")
        first_token = _link(sender)
        await client.post(
            "/applicant/access-links/open",
            json={"token": first_token, "switchCurrent": False},
        )
        await _save_draft(client, email="second@example.com")
        second_token = _link(sender)
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
    app, db, sender = _app_and_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await _save_draft(client, email="first@example.com")
        await client.post(
            "/applicant/access-links/open",
            json={"token": _link(sender), "switchCurrent": False},
        )
        await _save_draft(client, email="second@example.com")
        second_token = _link(sender)
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
@pytest.mark.parametrize(
    ("existing_time_offset", "expected_introduction"),
    [
        pytest.param(timedelta(minutes=-1), "Synthetic introduction", id="draft-newer"),
        pytest.param(timedelta(0), "Synthetic introduction", id="equal-prefers-draft"),
        pytest.param(timedelta(minutes=1), "Existing working answers", id="existing-newer"),
    ],
)
async def test_claim_keeps_newest_private_working_copy(
    existing_time_offset: timedelta,
    expected_introduction: str,
) -> None:
    app, db, sender = _app_and_db()
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
        await _save_draft(client)
        draft = db.scalar(select(ApplicantDraft))
        assert draft is not None
        save_working_copy(
            existing,
            WorkingApplicationAnswers.model_validate(
                _answers(introduction="Existing working answers")
            ),
            saved_at=as_utc(draft.saved_at) + existing_time_offset,
        )
        db.commit()
        opened = await client.post(
            "/applicant/access-links/open",
            json={"token": _link(sender), "switchCurrent": False},
        )
        stored = await client.get("/applicant/application")

    db.refresh(existing)
    db.refresh(draft)
    assert opened.status_code == 200
    assert stored.json()["answers"]["essays"]["householdIntroduction"] == (
        expected_introduction
    )
    assert existing.raw_row == {"submitted": "unchanged"}
    assert draft.resolved_at is not None


@pytest.mark.anyio
async def test_draft_past_its_opening_retention_date_cannot_be_opened_or_regenerated() -> None:
    app, db, sender = _app_and_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await _save_draft(client)
        token = _link(sender)
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


@pytest.mark.anyio
async def test_authenticated_submission_requires_declaration_and_accepts_multiple_openings() -> None:
    app, db, sender = _app_and_db()
    opening = db.scalar(select(Opening))
    assert opening is not None
    later_opening = Opening(
        unit_size_bedrooms=3,
        housing_charge_cents=150_000,
        application_open_date=opening.application_open_date,
        application_close_date=opening.application_close_date,
        move_in_date=opening.move_in_date + timedelta(days=30),
        published_at=datetime.now(UTC),
    )
    db.add(later_opening)
    db.commit()
    submitted_answers = _answers()
    submitted_answers["applicantEmployment"] = {
        "status": "unemployed",
        "jobTitle": None,
        "companyName": None,
        "startDate": None,
        "manager": None,
    }
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await _save_draft(client, intent="submit")
        await client.post(
            "/applicant/access-links/open",
            json={"token": _link(sender), "switchCurrent": False},
        )
        restored_before_submit = await client.get("/applicant/application")
        rejected = await client.post(
            "/applicant/application/submit",
            json={
                "answers": _answers(),
                "openingIds": [opening.id, later_opening.id],
                "declarationAccepted": False,
            },
        )
        submitted = await client.post(
            "/applicant/application/submit",
            json={
                "answers": submitted_answers,
                "openingIds": [opening.id, later_opening.id],
                "declarationAccepted": True,
                "baseRevision": restored_before_submit.json()["workingRevision"],
            },
        )
        restored = await client.get("/applicant/application")

    assert rejected.status_code == 422
    assert submitted.status_code == 200
    assert submitted.json()["answers"] == submitted_answers
    assert all(opening["participating"] for opening in submitted.json()["openings"])
    saved_at = datetime.fromisoformat(submitted.json()["workingSavedAt"])
    assert saved_at.utcoffset() == timedelta(0)
    assert restored.status_code == 200
    assert restored.json()["answers"] == submitted_answers
    assert set(db.scalars(select(ApplicationParticipation.opening_id))) == {
        opening.id,
        later_opening.id,
    }
    version = db.scalar(select(ApplicationVersion))
    assert version is not None
    assert version.selected_opening_ids == [opening.id, later_opening.id]


@pytest.mark.anyio
async def test_stale_browser_cannot_overwrite_a_newer_working_copy() -> None:
    app, db, sender = _app_and_db()
    opening = db.scalar(select(Opening))
    assert opening is not None
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await _save_draft(client)
        await client.post(
            "/applicant/access-links/open",
            json={"token": _link(sender), "switchCurrent": False},
        )
        restored = await client.get("/applicant/application")
        revision = restored.json()["workingRevision"]
        first_answers = _answers(introduction="Saved by the first browser")
        second_answers = _answers(introduction="Stale second browser")
        first = await client.put(
            "/applicant/application",
            json={
                "answers": first_answers,
                "openingIds": [opening.id],
                "baseRevision": revision,
            },
        )
        stale = await client.put(
            "/applicant/application",
            json={
                "answers": second_answers,
                "openingIds": [opening.id],
                "baseRevision": revision,
            },
        )
        latest = await client.get("/applicant/application")

    assert first.status_code == 200
    assert stale.status_code == 409
    assert stale.json()["code"] == "stale_application"
    assert latest.json()["answers"]["essays"]["householdIntroduction"] == (
        "Saved by the first browser"
    )


@pytest.mark.anyio
async def test_revert_restores_the_submitted_answers_and_openings() -> None:
    app, db, sender = _app_and_db()
    opening = db.scalar(select(Opening))
    assert opening is not None
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await _save_draft(client)
        await client.post(
            "/applicant/access-links/open",
            json={"token": _link(sender), "switchCurrent": False},
        )
        restored = await client.get("/applicant/application")
        submitted_answers = _answers(introduction="Committee copy")
        submitted = await client.post(
            "/applicant/application/submit",
            json={
                "answers": submitted_answers,
                "openingIds": [opening.id],
                "declarationAccepted": True,
                "baseRevision": restored.json()["workingRevision"],
            },
        )
        private_answers = _answers(introduction="Private edit")
        saved = await client.put(
            "/applicant/application",
            json={
                "answers": private_answers,
                "openingIds": [],
                "baseRevision": submitted.json()["workingRevision"],
            },
        )
        reverted = await client.post(
            "/applicant/application/revert",
            json={"baseRevision": saved.json()["workingRevision"]},
        )

    assert saved.json()["hasUnsubmittedChanges"] is True
    assert not any(item["selected"] for item in saved.json()["openings"])
    assert reverted.status_code == 200
    assert reverted.json()["answers"] == submitted_answers
    assert reverted.json()["hasUnsubmittedChanges"] is False
    selected = [item for item in reverted.json()["openings"] if item["selected"]]
    assert [item["id"] for item in selected] == [opening.id]


@pytest.mark.anyio
async def test_delete_withdraws_every_opening_and_revokes_applicant_access() -> None:
    app, db, sender = _app_and_db()
    opening = db.scalar(select(Opening))
    assert opening is not None
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await _save_draft(client)
        await client.post(
            "/applicant/access-links/open",
            json={"token": _link(sender), "switchCurrent": False},
        )
        restored = await client.get("/applicant/application")
        await client.post(
            "/applicant/application/submit",
            json={
                "answers": _answers(),
                "openingIds": [opening.id],
                "declarationAccepted": True,
                "baseRevision": restored.json()["workingRevision"],
            },
        )
        deleted = await client.delete("/applicant/application")
        after_delete = await client.get("/applicant/application")
        deletion_message_kind = sender.messages[-1].kind
        requested_again = await client.post(
            "/applicant/access-links/request",
            json={"answers": _answers(), "openingIds": [opening.id]},
        )

    application = db.scalar(select(Application))
    participation = db.scalar(select(ApplicationParticipation))
    assert deleted.status_code == 200
    assert deleted.json() == {
        "deleted": True,
        "emailSent": True,
        "emailStatus": "sent",
    }
    assert after_delete.status_code == 401
    assert application is not None
    assert application.deleted_at is not None
    assert participation is not None
    assert participation.withdrawn_at is not None
    assert all(session.revoked_at is not None for session in db.scalars(select(BrowserSession)))
    assert deletion_message_kind == "application_deleted"
    assert requested_again.json()["emailStatus"] == "sent"
    assert sender.messages[-1].kind == "applicant_magic_link"


@pytest.mark.anyio
async def test_delete_physically_removes_a_never_submitted_application() -> None:
    app, db, sender = _app_and_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await _save_draft(client)
        await client.post(
            "/applicant/access-links/open",
            json={"token": _link(sender), "switchCurrent": False},
        )
        deleted = await client.delete("/applicant/application")

    assert deleted.status_code == 200
    assert db.scalar(select(Application)) is None
    assert db.scalar(select(ApplicantDraft)) is None
    assert db.scalar(select(MagicLinkToken)) is None
    assert db.scalar(select(BrowserSession)) is None
    assert sender.messages[-1].kind == "application_deleted"
    assert "deleted from our system" in sender.messages[-1].text_body
    assert "removed from consideration" not in sender.messages[-1].text_body
    assert "https://www.pentacoop.com/apply.html" in sender.messages[-1].text_body


@pytest.mark.anyio
async def test_deleted_email_can_start_a_new_blank_application() -> None:
    app, db, sender = _app_and_db()
    opening = db.scalar(select(Opening))
    assert opening is not None
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        first = await client.post(
            "/applicant/submissions",
            json={
                "answers": _answers(),
                "openingIds": [opening.id],
                "declarationAccepted": True,
            },
        )
        await client.post(
            "/applicant/access-links/open",
            json={"token": _link(sender), "switchCurrent": False},
        )
        deleted = await client.delete("/applicant/application")
        second_answers = _answers(introduction="A completely new application")
        second = await client.post(
            "/applicant/submissions",
            json={
                "answers": second_answers,
                "openingIds": [opening.id],
                "declarationAccepted": True,
            },
        )

    applications = list(db.scalars(select(Application).order_by(Application.id)))
    assert first.status_code == 201
    assert deleted.status_code == 200
    assert second.status_code == 201
    assert len(applications) == 2
    assert applications[0].deleted_at is not None
    assert applications[1].deleted_at is None
    assert applications[1].raw_row["essays"]["household_introduction"] == (
        "A completely new application"
    )
