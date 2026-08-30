from datetime import UTC, datetime, timedelta

import pytest
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.time import pacific_today
from app.db.models import (
    ApplicantDraft,
    Application,
    ApplicationParticipation,
    ApplicationVersion,
    MagicLinkToken,
    Opening,
)
from app.services.email_sender import get_email_sender
from tests.applicant.support import (
    FailingEmailSender,
    app_and_db,
    link_from_email,
    sample_answers,
    save_draft,
)


@pytest.mark.anyio
async def test_save_immediately_persists_private_draft_and_sends_access_link() -> None:
    app, db, _sender = app_and_db()
    transport = ASGITransport(app=app)
    before = datetime.now(UTC)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await save_draft(client)

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
    app, db, _sender = app_and_db()
    app.dependency_overrides[get_email_sender] = lambda: FailingEmailSender()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await save_draft(client)

    draft = db.scalar(select(ApplicantDraft))
    assert response.status_code == 202
    assert response.json()["emailSent"] is False
    assert draft is not None
    assert draft.revoked_at is None
    assert draft.working_answers is not None


@pytest.mark.anyio
async def test_delivery_failure_does_not_suppress_an_immediate_retry() -> None:
    app, db, _sender = app_and_db()
    app.dependency_overrides[get_email_sender] = lambda: FailingEmailSender()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        opening = db.scalar(select(Opening))
        assert opening is not None
        request = {"answers": sample_answers(), "openingIds": [opening.id]}
        first = await client.post("/applicant/access-links/request", json=request)
        second = await client.post("/applicant/access-links/request", json=request)

    assert first.json()["emailStatus"] == "failed"
    assert second.json()["emailStatus"] == "failed"
    assert len(list(db.scalars(select(MagicLinkToken)))) == 2


@pytest.mark.anyio
async def test_save_and_return_later_accepts_an_incomplete_application() -> None:
    app, db, sender = app_and_db()
    answers = sample_answers()
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
    app, db, sender = app_and_db()
    opening = db.scalar(select(Opening))
    assert opening is not None
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/applicant/submissions",
            json={
                "answers": sample_answers(),
                "openingIds": [opening.id],
                "declarationAccepted": True,
            },
        )

    application = db.scalar(select(Application))
    assert response.status_code == 201
    assert response.json() == {"submitted": True}
    assert application is not None
    assert application.submitted_at is not None
    assert db.scalar(select(ApplicationVersion.application_id)) == application.id
    assert db.scalar(select(ApplicationParticipation.opening_id)) == opening.id
    assert len(sender.messages) == 1
    close_date = f"{opening.application_close_date.strftime('%B')} {opening.application_close_date.day}, {opening.application_close_date.year}"
    move_in_date = f"{opening.move_in_date.strftime('%B')} {opening.move_in_date.day}, {opening.move_in_date.year}"
    assert (
        f"we'll contact you between {close_date} and {move_in_date}"
        in sender.messages[0].text_body
    )
    assert (
        f"Whether or not you're shortlisted, we'll email you shortly after {move_in_date}"
        in sender.messages[0].text_body
    )
    assert "update your application or delete your profile" in sender.messages[0].text_body


@pytest.mark.anyio
async def test_guest_with_existing_email_is_stopped_before_review_and_sent_access() -> None:
    app, _db, sender = app_and_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await save_draft(client)
        await client.post(
            "/applicant/access-links/open",
            json={"token": link_from_email(sender), "switchCurrent": False},
        )
        await client.post("/applicant/auth/logout")
        response = await client.post(
            "/applicant/submissions/check",
            json={"answers": sample_answers(introduction="Guest answers"), "openingIds": [1]},
        )

    assert response.status_code == 200
    assert response.json() == {
        "canSubmit": False,
        "emailSent": True,
        "emailStatus": "sent",
    }
    assert len(sender.messages) == 2
    draft = _db.scalar(
        select(ApplicantDraft).where(ApplicantDraft.resolved_at.is_(None))
    )
    assert draft is not None
    assert draft.working_answers["essays"]["household_introduction"] == "Guest answers"


@pytest.mark.anyio
async def test_repeated_guest_collision_updates_the_copy_for_the_link_already_sent() -> None:
    app, db, sender = app_and_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await save_draft(client)
        await client.post(
            "/applicant/access-links/open",
            json={"token": link_from_email(sender), "switchCurrent": False},
        )
        await client.post("/applicant/auth/logout")
        sender.messages.clear()
        first = await client.post(
            "/applicant/submissions/check",
            json={"answers": sample_answers(introduction="First guest copy"), "openingIds": [1]},
        )
        token = link_from_email(sender)
        second = await client.post(
            "/applicant/submissions/check",
            json={"answers": sample_answers(introduction="Latest guest copy"), "openingIds": [1]},
        )
        opened = await client.post(
            "/applicant/access-links/open",
            json={"token": token, "switchCurrent": False},
        )

    drafts = list(
        db.scalars(select(ApplicantDraft).where(ApplicantDraft.resolved_at.is_(None)))
    )
    assert first.json()["emailStatus"] == "sent"
    assert second.json()["emailStatus"] == "recent"
    assert len(sender.messages) == 1
    assert len(drafts) == 1
    assert opened.json()["pendingCopy"]["guestAnswers"]["essays"]["householdIntroduction"] == "Latest guest copy"


@pytest.mark.anyio
async def test_return_link_request_does_not_reveal_whether_application_exists() -> None:
    app, db, sender = app_and_db()
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
            json={"answers": sample_answers("returning@example.com", "Ignored browser answers")},
        )
        missing = await client.post(
            "/applicant/access-links/request",
            json={"answers": sample_answers("missing@example.com", "New saved draft")},
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
    app, db, sender = app_and_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await save_draft(client)
        original_link = db.scalar(select(MagicLinkToken))
        assert original_link is not None
        original_link.created_at = datetime.now(UTC) - timedelta(minutes=10)
        db.commit()
        sender.messages.clear()

        response = await client.post(
            "/applicant/access-links/request",
            json={"answers": sample_answers(introduction="Ignored replacement")},
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
async def test_email_entry_with_multiple_openings_does_not_preselect_one() -> None:
    app, db, sender = app_and_db()
    opening = db.scalar(select(Opening))
    assert opening is not None
    db.add(
        Opening(
            unit_size_bedrooms=3,
            housing_charge_cents=150_000,
            application_open_date=opening.application_open_date,
            application_close_date=opening.application_close_date,
            move_in_date=opening.move_in_date,
            published_at=datetime.now(UTC),
        )
    )
    db.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/applicant/access-links/request",
            json={"answers": sample_answers("new@example.com"), "openingIds": []},
        )

    draft = db.scalar(select(ApplicantDraft))
    assert response.status_code == 202
    assert draft is not None
    assert draft.working_opening_ids == []
    assert draft.retention_due_on > pacific_today()
    assert len(sender.messages) == 1


@pytest.mark.anyio
async def test_existing_applicant_without_an_actionable_opening_receives_public_update() -> None:
    app, db, sender = app_and_db()
    opening = db.scalar(select(Opening))
    assert opening is not None
    opening.application_close_date = pacific_today() - timedelta(days=2)
    opening.move_in_date = pacific_today() - timedelta(days=1)
    application = Application(
        primary_email="returning@example.com",
        applicant_name="Synthetic Returning Applicant",
        raw_row=sample_answers("returning@example.com"),
        raw_row_hash="synthetic-submitted",
        normalized={},
        working_answers=sample_answers("returning@example.com"),
        working_content_hash="synthetic-working",
        working_saved_at=datetime.now(UTC),
    )
    db.add(application)
    db.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/applicant/access-links/request",
            json={"answers": sample_answers("returning@example.com")},
        )

    assert response.status_code == 202
    assert response.json()["emailStatus"] == "sent"
    assert len(sender.messages) == 1
    assert sender.messages[0].kind == "application_unavailable"
    assert "https://www.pentacoop.com/apply.html" in sender.messages[0].text_body
    assert db.scalar(select(MagicLinkToken)) is None


@pytest.mark.anyio
async def test_unknown_address_without_an_actionable_opening_receives_public_update() -> None:
    app, db, sender = app_and_db()
    opening = db.scalar(select(Opening))
    assert opening is not None
    opening.application_close_date = pacific_today() - timedelta(days=2)
    opening.move_in_date = pacific_today() - timedelta(days=1)
    db.commit()
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/applicant/access-links/request",
            json={"answers": sample_answers("unknown@example.com")},
        )

    assert response.status_code == 202
    assert response.json()["emailStatus"] == "sent"
    assert len(sender.messages) == 1
    assert sender.messages[0].kind == "application_unavailable"
    assert sender.messages[0].to == ("unknown@example.com",)
    assert db.scalar(select(ApplicantDraft)) is None
    assert db.scalar(select(MagicLinkToken)) is None
