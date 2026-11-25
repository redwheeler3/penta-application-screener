"""Anonymous admission limits precede records and mail, regardless of mailbox or endpoint."""

import pytest
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.api.applicant.guest import guest_limiter
from app.db.models import ApplicantDraft, Application, Opening
from tests.applicant.support import (
    app_and_db,
    link_from_email,
    sample_answers,
    save_draft,
)


@pytest.fixture(autouse=True)
def clear_admission_quota():
    guest_limiter.clear()
    yield
    guest_limiter.clear()


@pytest.mark.anyio
@pytest.mark.parametrize("endpoint", ["drafts", "submissions", "submissions/check", "access-links/request"])
async def test_anonymous_limits_precede_record_creation_and_mail(endpoint):
    app, db, sender = app_and_db()
    opening = db.scalar(select(Opening))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        for index in range(guest_limiter.limit):
            body = {"answers": sample_answers(f"synthetic-{index}@example.com"), "openingIds": [opening.id]}
            if endpoint == "drafts":
                body["intent"] = "save"
            if endpoint == "submissions":
                body["declarationAccepted"] = True
            response = await client.post(f"/applicant/{endpoint}", json=body,
                headers={"X-Forwarded-For": f"192.0.2.{index + 1}", "Fly-Client-IP": f"192.0.2.{index + 1}"})
            assert response.is_success
        counts = [db.scalar(select(func.count()).select_from(model)) for model in [Application, ApplicantDraft]]
        messages = len(sender.messages)
        # One quota covers the other public entry paths too, not only this endpoint.
        response = await client.post("/applicant/drafts", json={"answers": sample_answers(), "intent": "save"})
        assert response.status_code == 429
        assert [db.scalar(select(func.count()).select_from(model)) for model in [Application, ApplicantDraft]] == counts
        assert len(sender.messages) == messages


@pytest.mark.anyio
async def test_authenticated_revision_save_is_not_blocked_by_anonymous_quota():
    app, _db, sender = app_and_db()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        await save_draft(client)
        await client.post("/applicant/access-links/open", json={"token": link_from_email(sender), "switchCurrent": False})
        current = (await client.get("/applicant/application")).json()
        while guest_limiter.allow("127.0.0.1"):
            pass
        response = await client.post("/applicant/access-links/request", json={"answers": sample_answers(),
            "openingIds": [1], "baseRevision": current["workingRevision"]})
        assert response.status_code == 202
        assert response.json()["currentAnswersSaved"] is True
