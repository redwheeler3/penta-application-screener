from datetime import UTC, datetime, timedelta

import pytest
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import select

from app.db.models import (
    ApplicantDraft,
    Application,
    ApplicationParticipation,
    ApplicationVersion,
    BrowserSession,
    MagicLinkToken,
    Opening,
)
from app.legal import APPLICATION_TERMS_VERSION
from app.services.retention import one_year_after
from tests.applicant.support import (
    app_and_db,
    link_from_email,
    sample_answers,
    save_draft,
)


@pytest.mark.anyio
async def test_authenticated_submission_requires_declaration_and_accepts_multiple_openings() -> None:
    app, db, sender = app_and_db()
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
    submitted_answers = sample_answers()
    submitted_answers["applicantEmployment"] = {
        "status": "unemployed",
        "jobTitle": None,
        "companyName": None,
        "startDate": None,
        "manager": None,
    }
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await save_draft(client, intent="submit")
        await client.post(
            "/applicant/access-links/open",
            json={"token": link_from_email(sender), "switchCurrent": False},
        )
        restored_before_submit = await client.get("/applicant/application")
        rejected = await client.post(
            "/applicant/application/submit",
            json={
                "answers": sample_answers(),
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
    assert version.terms_version == APPLICATION_TERMS_VERSION


@pytest.mark.anyio
async def test_stale_browser_cannot_overwrite_a_newer_working_copy() -> None:
    app, db, sender = app_and_db()
    opening = db.scalar(select(Opening))
    assert opening is not None
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await save_draft(client)
        await client.post(
            "/applicant/access-links/open",
            json={"token": link_from_email(sender), "switchCurrent": False},
        )
        restored = await client.get("/applicant/application")
        revision = restored.json()["workingRevision"]
        first_answers = sample_answers(introduction="Saved by the first browser")
        second_answers = sample_answers(introduction="Stale second browser")
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
    app, db, sender = app_and_db()
    opening = db.scalar(select(Opening))
    assert opening is not None
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await save_draft(client)
        await client.post(
            "/applicant/access-links/open",
            json={"token": link_from_email(sender), "switchCurrent": False},
        )
        restored = await client.get("/applicant/application")
        submitted_answers = sample_answers(introduction="Committee copy")
        submitted = await client.post(
            "/applicant/application/submit",
            json={
                "answers": submitted_answers,
                "openingIds": [opening.id],
                "declarationAccepted": True,
                "baseRevision": restored.json()["workingRevision"],
            },
        )
        private_answers = sample_answers(introduction="Private edit")
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
async def test_withdrawal_removes_every_opening_and_revokes_applicant_access() -> None:
    app, db, sender = app_and_db()
    opening = db.scalar(select(Opening))
    assert opening is not None
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await save_draft(client)
        await client.post(
            "/applicant/access-links/open",
            json={"token": link_from_email(sender), "switchCurrent": False},
        )
        restored = await client.get("/applicant/application")
        await client.post(
            "/applicant/application/submit",
            json={
                "answers": sample_answers(),
                "openingIds": [opening.id],
                "declarationAccepted": True,
                "baseRevision": restored.json()["workingRevision"],
            },
        )
        messages_before_withdrawal = len(sender.messages)
        withdrawn = await client.post("/applicant/application/withdraw")
        after_delete = await client.get("/applicant/application")
        messages_after_withdrawal = len(sender.messages)
        requested_again = await client.post(
            "/applicant/access-links/request",
            json={"answers": sample_answers(), "openingIds": [opening.id]},
        )

    application = db.scalar(select(Application))
    participation = db.scalar(select(ApplicationParticipation))
    assert withdrawn.status_code == 200
    assert withdrawn.json() == {"withdrawn": True}
    assert after_delete.status_code == 401
    assert application is not None
    assert application.withdrawn_at is not None
    assert application.retention_due_on == one_year_after(opening.move_in_date)
    assert participation is not None
    assert participation.withdrawn_at is not None
    assert all(session.revoked_at is not None for session in db.scalars(select(BrowserSession)))
    assert messages_after_withdrawal == messages_before_withdrawal
    assert requested_again.json()["emailStatus"] == "sent"
    assert sender.messages[-1].kind == "applicant_magic_link"


@pytest.mark.anyio
async def test_delete_physically_removes_a_never_submitted_application() -> None:
    app, db, sender = app_and_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await save_draft(client)
        await client.post(
            "/applicant/access-links/open",
            json={"token": link_from_email(sender), "switchCurrent": False},
        )
        withdrawn = await client.post("/applicant/application/withdraw")

    assert withdrawn.status_code == 200
    assert withdrawn.json() == {"withdrawn": True}
    assert db.scalar(select(Application)) is None
    assert db.scalar(select(ApplicantDraft)) is None
    assert db.scalar(select(MagicLinkToken)) is None
    assert db.scalar(select(BrowserSession)) is None
    assert [message.kind for message in sender.messages] == ["applicant_magic_link"]


@pytest.mark.anyio
async def test_withdrawn_applicant_can_start_a_new_blank_application() -> None:
    app, db, sender = app_and_db()
    opening = db.scalar(select(Opening))
    assert opening is not None
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        first = await client.post(
            "/applicant/submissions",
            json={
                "answers": sample_answers(),
                "openingIds": [opening.id],
                "declarationAccepted": True,
            },
        )
        await client.post(
            "/applicant/access-links/open",
            json={"token": link_from_email(sender), "switchCurrent": False},
        )
        withdrawn = await client.post("/applicant/application/withdraw")
        second_answers = sample_answers(introduction="A completely new application")
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
    assert withdrawn.status_code == 200
    assert second.status_code == 201
    assert len(applications) == 2
    assert applications[0].withdrawn_at is not None
    assert applications[1].withdrawn_at is None
    assert applications[1].raw_row["essays"]["household_introduction"] == (
        "A completely new application"
    )
