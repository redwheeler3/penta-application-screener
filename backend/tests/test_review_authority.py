"""A saved human decision only acknowledges the findings that member actually viewed."""

from datetime import UTC, datetime

import pytest
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import select

from app.ai.schemas import FlagCategory, ScreeningFlag, ScreeningReport
from app.db.models import MemberEligibility, Opening, UserRole
from app.schemas.applicant.answers import CanonicalApplicationAnswers
from app.services.applications.intake import publish_working_copy
from tests.applicant.support import sample_answers
from tests.committee_app_support import add_eligible_application, setup_committee_app


@pytest.mark.anyio
@pytest.mark.parametrize("change", ["submission", "screen"])
async def test_decision_preserves_viewed_findings_until_member_reaffirms(change):
    app, db, provider = setup_committee_app(role=UserRole.MEMBER)
    application = add_eligible_application(db, email="synthetic@example.com", raw_hash="initial")
    opening = db.scalar(select(Opening))
    answers = sample_answers(application.primary_email)
    answers["children"] = [{"firstName": "Synthetic", "lastName": "Child", "birthDate": "2020-01-01"}]
    publish_working_copy(db, application, CanonicalApplicationAnswers.model_validate(answers),
                         [opening], submitted_at=datetime.now(UTC))
    db.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        viewed = (await client.get(f"/applications/{application.id}")).json()["application"]
        assert viewed["hardFilterReasons"] == []
        if change == "submission":
            answers["applicantIncome"] = 100
            publish_working_copy(db, application, CanonicalApplicationAnswers.model_validate(answers),
                                 [opening], submitted_at=datetime.now(UTC))
            db.commit()
        else:
            provider.queue(ScreeningReport(flags=[ScreeningFlag(category=FlagCategory.FAKE_CONTACT,
                summary="Synthetic new finding", evidence="Synthetic evidence")]))
            assert (await client.post("/screening/run")).status_code == 200
        saved = await client.patch(f"/applications/{application.id}/status", json={
            "status": "eligible", "reviewedFingerprint": viewed["findingsFingerprint"]})
        assert saved.status_code == 200
        assert saved.json()["application"]["status"] == "eligible"
        assert saved.json()["application"]["stale"] is True
        assert db.scalar(select(MemberEligibility)).reviewed_fingerprint == viewed["findingsFingerprint"]
        current = (await client.get(f"/applications/{application.id}")).json()["application"]
        assert current["findingsFingerprint"] != viewed["findingsFingerprint"]
        assert current["stale"] is True
        reaffirmed = await client.patch(f"/applications/{application.id}/status", json={
            "status": "eligible", "reviewedFingerprint": current["findingsFingerprint"]})
        assert reaffirmed.status_code == 200
        assert reaffirmed.json()["application"]["stale"] is False


@pytest.mark.anyio
async def test_review_requires_displayed_evidence_but_automatic_clear_does_not():
    app, db, _ = setup_committee_app(role=UserRole.MEMBER)
    application = add_eligible_application(db, email="synthetic@example.com", raw_hash="initial")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        missing = await client.patch(f"/applications/{application.id}/status", json={"status": "eligible"})
        assert missing.status_code == 422
        assert db.scalar(select(MemberEligibility)) is None
        cleared = await client.delete(f"/applications/{application.id}/status")
        assert cleared.status_code == 200
        assert cleared.json()["application"]["statusSource"] == "untouched"
