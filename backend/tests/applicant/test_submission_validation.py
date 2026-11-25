"""Only new publication requires the complete set of applicable form answers."""

from copy import deepcopy
from pathlib import Path

import pytest
from httpx2 import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy import func, select

from app.api.session_cookie import SESSION_COOKIE_NAMES
from app.db.models import (
    Application,
    ApplicationVersion,
    Opening,
    PasswordlessIdentityKind,
)
from app.schemas.applicant.answers import (
    CanonicalApplicationAnswers,
    WorkingApplicationAnswers,
)
from app.schemas.applicant.contracts import (
    SubmitApplicationRequest,
)
from app.services.applications.synthetic_fixture import read_synthetic_fixture
from app.services.auth.passwordless import create_browser_session
from tests.applicant.support import app_and_db, sample_answers


def complete_answers():
    answers = sample_answers()
    answers["coApplicant"] = {**answers["applicant"], "email": "co@example.com", "relationship": "Partner"}
    answers["coApplicantEmployment"] = deepcopy(answers["applicantEmployment"])
    answers["coApplicantIncome"] = 0
    answers["children"] = [{"firstName": "Child", "lastName": "Example", "birthDate": "2020-01-01"}]
    answers["currentAddressMoveInDate"] = "2025-01-01"
    answers["previousResidences"] = [{"address": deepcopy(answers["currentAddress"]), "moveInDate": "2020-01-01"}]
    answers["previousLandlord"] = deepcopy(answers["currentLandlord"])
    return answers


REQUIRED_TEXT = [
    *((person, field) for person in ("applicant", "coApplicant") for field in ("firstName", "lastName", "phone")),
    ("coApplicant", "relationship"),
    *(("children", 0, field) for field in ("firstName", "lastName")),
    *(("currentAddress", field) for field in ("street", "city", "provinceOrState", "postalOrZipCode", "country")),
    *(("previousResidences", 0, "address", field) for field in ("street", "city", "provinceOrState", "postalOrZipCode", "country")),
    *((reference, field) for reference in ("currentLandlord", "previousLandlord") for field in ("name", "phone")),
    *((employment, field) for employment in ("applicantEmployment", "coApplicantEmployment") for field in ("jobTitle", "companyName")),
    *((employment, "manager", field) for employment in ("applicantEmployment", "coApplicantEmployment") for field in ("name", "phone")),
    *(("essays", field) for field in ("householdIntroduction", "skillsToContribute", "previousCoopExperience", "whyCoop")),
]


@pytest.mark.parametrize("path", REQUIRED_TEXT, ids=lambda path: ".".join(map(str, path)))
def test_publication_rejects_each_blank_applicable_text_answer(path):
    answers = complete_answers()
    target = answers
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = " \t\n"
    with pytest.raises(ValidationError, match="required"):
        SubmitApplicationRequest.model_validate({"answers": answers, "openingIds": [1]})


@pytest.mark.parametrize("field", ["coApplicantEmployment", "coApplicantIncome"])
def test_present_co_applicant_needs_employment_and_income(field):
    answers = complete_answers()
    answers[field] = None
    with pytest.raises(ValidationError, match=r"Co-applicant.*required"):
        SubmitApplicationRequest.model_validate({"answers": answers, "openingIds": [1]})


@pytest.mark.parametrize("employment", ["unemployed", "self_employed"])
def test_optional_and_inapplicable_answers_do_not_block_submission(employment):
    answers = complete_answers()
    answers.update(coApplicant=None, coApplicantEmployment=None, coApplicantIncome=None,
                   children=[], ownsCurrentHome=True, currentLandlord=None, previousLandlord=None,
                   pets=None, householdPhotoLink=None)
    answers["essays"]["additionalInformation"] = ""
    answers["currentAddress"]["street2"] = None
    answers["applicantEmployment"].update(status=employment, manager=None)
    request = SubmitApplicationRequest.model_validate({"answers": answers, "openingIds": [1]})
    assert request.answers.applicant_employment.manager is None


def test_private_retained_and_synthetic_answers_remain_tolerant():
    answers = complete_answers()
    answers["essays"]["whyCoop"] = ""
    answers["coApplicantEmployment"] = None
    answers["coApplicantIncome"] = None
    assert CanonicalApplicationAnswers.model_validate(answers).essays.why_coop == ""
    assert WorkingApplicationAnswers.model_validate(answers).co_applicant_employment is None
    fixture = Path(__file__).resolve().parents[3] / "test-data" / "synthetic-penta-application-responses.csv"
    assert len(list(read_synthetic_fixture(fixture))) == 100


@pytest.mark.anyio
@pytest.mark.parametrize("authenticated", [False, True])
async def test_incomplete_publication_cannot_change_durable_answers(authenticated):
    app, db, _sender = app_and_db()
    opening_id = db.scalar(select(Opening.id))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        payload = {"answers": sample_answers(), "openingIds": [opening_id], "declarationAccepted": True}
        if authenticated:
            assert (await client.post("/applicant/submissions", json=payload)).status_code == 201
            application = db.scalar(select(Application))
            before = deepcopy(application.raw_row)
            revision = application.working_revision
            issued = create_browser_session(db, identity_kind=PasswordlessIdentityKind.APPLICANT,
                                            application_id=application.id)
            db.commit()
            client.cookies.set(SESSION_COOKIE_NAMES[PasswordlessIdentityKind.APPLICANT], issued.token)
            client.headers["X-Penta-Identity"] = f"applicant:{application.id}"
            payload["baseRevision"] = revision
        payload["answers"]["essays"]["whyCoop"] = ""
        response = await client.post("/applicant/application/submit" if authenticated else "/applicant/submissions", json=payload)
    assert response.status_code == 422
    assert db.scalar(select(func.count()).select_from(ApplicationVersion)) == int(authenticated)
    if authenticated:
        db.refresh(application)
        assert application.raw_row == before
        assert application.working_revision == revision
    else:
        assert db.scalar(select(Application)) is None


def test_applicant_calendar_matches_validation_on_both_sides_of_vancouver_midnight():
    from datetime import UTC, date, datetime, time, timedelta
    from unittest.mock import patch

    from pydantic import ValidationError

    from app.core.time import PACIFIC, pacific_today
    from app.schemas.applicant.answers import EmploymentAnswers
    from app.schemas.applicant.contracts import ApplicantCalendar

    for day in (date(2026, 7, 25), date(2026, 11, 25)):
        midnight = datetime.combine(day, time.min, tzinfo=PACIFIC).astimezone(UTC)
        for offset in (timedelta(milliseconds=-1), timedelta(), timedelta(minutes=30)):
            instant = midnight + offset
            calendar = ApplicantCalendar.current(instant)
            assert calendar.today == pacific_today(now=instant)
            next_midnight = instant + timedelta(milliseconds=calendar.milliseconds_until_midnight)
            assert pacific_today(now=next_midnight) == calendar.today + timedelta(days=1)
            payload = {"status": "self_employed", "jobTitle": "Fiction", "companyName": "Fiction", "startDate": day}
            with patch("app.schemas.applicant.answers.pacific_today", return_value=calendar.today):
                if offset < timedelta():
                    with pytest.raises(ValidationError, match="future"):
                        EmploymentAnswers.model_validate(payload)
                else:
                    assert EmploymentAnswers.model_validate(payload).start_date == day
