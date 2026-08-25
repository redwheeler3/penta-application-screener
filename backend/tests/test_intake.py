from datetime import UTC, date, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.time import as_utc
from app.db.models import (
    Application,
    ApplicationParticipation,
    ApplicationVersion,
    Base,
    Opening,
)
from app.domain.hard_filters import RulesConfig
from app.schemas.intake import (
    AddressAnswers,
    CanonicalApplicationAnswers,
    ChildAnswers,
    CoApplicantAnswers,
    EmploymentAnswers,
    EssayAnswers,
    PersonAnswers,
    ReferenceAnswers,
)
from app.services.intake import (
    canonical_answers,
    content_hash,
    normalize_answers,
    publish_working_copy,
    save_working_copy,
)
from app.services.rules import hard_filter_reasons_for


def _answers() -> CanonicalApplicationAnswers:
    reference = ReferenceAnswers(name="Synthetic Reference", email="ref@example.com", phone="604-555-0101")
    return CanonicalApplicationAnswers(
        applicant=PersonAnswers(
            first_name="Avery",
            last_name="Example",
            birth_date=date(1988, 4, 12),
            phone="604-555-0100",
            email="avery@example.com",
        ),
        co_applicant=CoApplicantAnswers(
            first_name="Morgan",
            last_name="Example",
            birth_date=date(1989, 5, 13),
            phone="(604) 555-0102",
            email="morgan@example.com",
            relationship="Partner",
        ),
        children=[ChildAnswers(first_name="Casey", last_name="Example", birth_date=date(2015, 6, 1))],
        current_address=AddressAnswers(
            street="1 Example Street",
            city="Vancouver",
            province_or_state="BC",
            postal_or_zip_code="V0V 0V0",
            country="Canada",
        ),
        lived_at_current_address_two_years=True,
        owns_current_home=False,
        owns_other_real_estate=False,
        current_landlord=reference,
        essays=EssayAnswers(
            household_introduction="Synthetic household introduction.",
            skills_to_contribute="Synthetic repair skills.",
            previous_coop_experience="Synthetic co-op experience.",
            why_coop="Synthetic interest in shared community work.",
        ),
        household_photo_link="https://example.com/synthetic-household-photo",
        applicant_employment=EmploymentAnswers(
            status="employed",
            job_title="Tester",
            company_name="Example Company",
            start_date=date(2020, 1, 1),
            manager=reference,
        ),
        applicant_income=70_000,
        co_applicant_income=20_000,
    )


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_canonical_answers_have_stable_content_hash_and_calculated_income() -> None:
    answers = _answers()
    stored = canonical_answers(answers)

    assert answers.household_income == 90_000
    assert stored["applicant"]["birth_date"] == "1988-04-12"
    assert stored["household_photo_link"] == "https://example.com/synthetic-household-photo"
    assert content_hash(stored) == content_hash({**stored})


def test_household_photo_link_must_be_a_web_address() -> None:
    data = _answers().model_dump()
    data["household_photo_link"] = "not a link"

    with pytest.raises(ValueError, match="URL"):
        CanonicalApplicationAnswers.model_validate(data)


def test_household_income_ignores_hidden_co_applicant_income() -> None:
    answers = _answers().model_copy(update={"co_applicant": None})

    assert answers.household_income == 70_000


def test_real_estate_fact_combines_current_home_and_other_property() -> None:
    answers = _answers()

    assert answers.owns_real_estate is False
    assert answers.model_copy(update={"owns_current_home": True}).owns_real_estate is True
    assert answers.model_copy(update={"owns_other_real_estate": True}).owns_real_estate is True


def test_housing_references_follow_current_home_and_residency_answers() -> None:
    homeowner = _answers().model_dump()
    homeowner.update(
        owns_current_home=True,
        lived_at_current_address_two_years=False,
        current_landlord=None,
        previous_landlord=None,
    )

    homeowner_answers = CanonicalApplicationAnswers.model_validate(homeowner)
    assert homeowner_answers.current_landlord is None
    assert homeowner_answers.previous_landlord is None

    renter_without_landlord = _answers().model_dump()
    renter_without_landlord["current_landlord"] = None
    with pytest.raises(ValueError, match="current landlord"):
        CanonicalApplicationAnswers.model_validate(renter_without_landlord)

    recent_mover = _answers().model_dump()
    recent_mover["lived_at_current_address_two_years"] = False
    with pytest.raises(ValueError, match="previous housing reference"):
        CanonicalApplicationAnswers.model_validate(recent_mover)


def test_canonical_answers_allow_every_child_without_intake_eligibility_block() -> None:
    data = _answers().model_dump()
    data["children"] = data["children"] * 5

    answers = CanonicalApplicationAnswers.model_validate(data)

    assert len(answers.children) == 5


def test_employment_status_controls_applicable_details() -> None:
    reference = ReferenceAnswers(
        name="Synthetic Reference",
        email="ref@example.com",
        phone="(604) 555-0101",
    )
    unemployed = EmploymentAnswers(
        status="unemployed",
        job_title="Stale hidden value",
        company_name="Stale hidden value",
        start_date=date(2020, 1, 1),
        manager=reference,
    )
    self_employed = EmploymentAnswers(
        status="self_employed",
        job_title="Consultant",
        company_name="Example Consulting",
        start_date=date(2022, 2, 1),
        manager=reference,
    )

    assert unemployed.job_title is None
    assert unemployed.manager is None
    assert self_employed.manager is None


def test_employed_applicant_requires_manager() -> None:
    with pytest.raises(ValueError, match="manager details"):
        EmploymentAnswers(
            status="employed",
            job_title="Tester",
            company_name="Example Company",
            start_date=date(2020, 1, 1),
        )


def test_working_copy_does_not_replace_submitted_projection() -> None:
    saved_at = datetime(2026, 8, 23, tzinfo=UTC)
    application = Application(
        primary_email="avery@example.com",
        applicant_name="Prior Applicant",
        raw_row={"legacy": "submitted"},
        raw_row_hash="submitted-hash",
        normalized={"applicant_name": "Prior Applicant"},
    )

    save_working_copy(application, _answers(), saved_at=saved_at)

    assert application.raw_row == {"legacy": "submitted"}
    assert application.raw_row_hash == "submitted-hash"
    assert application.working_answers is not None
    assert application.working_content_hash == content_hash(application.working_answers)
    assert application.working_saved_at == saved_at


def test_publication_records_participation_and_an_application_version() -> None:
    db = _session()
    submitted_at = datetime(2026, 8, 23, tzinfo=UTC)
    application = Application(
        primary_email="avery@example.com",
        raw_row={},
        raw_row_hash=content_hash({}),
        normalized={},
    )
    opening = Opening(
        unit_size_bedrooms=3,
        housing_charge_cents=120_000,
        application_open_date=date(2026, 8, 1),
        application_close_date=date(2026, 9, 1),
        move_in_date=date(2026, 10, 1),
        published_at=datetime(2026, 7, 1, tzinfo=UTC),
    )
    db.add_all([application, opening])
    db.flush()
    publish_working_copy(db, application, _answers(), [opening], submitted_at=submitted_at)
    db.commit()

    participation = db.query(ApplicationParticipation).one()
    assert participation.application_id == application.id
    assert as_utc(participation.applied_at) == submitted_at
    version = db.query(ApplicationVersion).one()
    assert version.application_id == application.id
    assert version.selected_opening_ids == [opening.id]
    assert version.content_hash == application.raw_row_hash
    assert application.normalized["household_photo_link"] == "https://example.com/synthetic-household-photo"
    assert version.answers["household_photo_link"] == "https://example.com/synthetic-household-photo"


def test_age_checks_are_anchored_to_last_submitted_edit() -> None:
    answers = _answers().model_copy(
        update={
            "applicant": _answers().applicant.model_copy(
                update={"birth_date": date(2008, 9, 15)}
            ),
            "co_applicant": _answers().co_applicant.model_copy(
                update={"birth_date": date(2008, 9, 10)}
            ),
            "children": [
                ChildAnswers(
                    first_name="Casey",
                    last_name="Example",
                    birth_date=date(2008, 9, 20),
                )
            ],
        }
    )
    application = Application(
        primary_email="avery@example.com",
        raw_row={},
        raw_row_hash=content_hash({}),
        normalized=normalize_answers(answers, as_of_date=date(2026, 9, 9)),
        submitted_at=datetime(2026, 9, 16, 18, tzinfo=UTC),
    )
    submitted_between_birthdays = hard_filter_reasons_for(
        RulesConfig(min_adult_age=18, max_child_age=17, today=date(2030, 1, 1)),
        application,
    )
    application.submitted_at = datetime(2026, 9, 21, 18, tzinfo=UTC)
    submitted_after_child_birthday = hard_filter_reasons_for(
        RulesConfig(min_adult_age=18, max_child_age=17, today=date(2030, 1, 1)),
        application,
    )

    assert not {
        "applicant_under_min_age",
        "co_applicant_under_min_age",
        "child_age_over_max",
    } & {reason["code"] for reason in submitted_between_birthdays}
    assert "child_age_over_max" in {
        reason["code"] for reason in submitted_after_child_birthday
    }
