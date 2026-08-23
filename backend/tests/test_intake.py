from datetime import UTC, date, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import (
    Application,
    ApplicationCycleSnapshot,
    ApplicationParticipation,
    Base,
    Opening,
    OpeningStatus,
)
from app.schemas.intake import (
    AddressAnswers,
    CanonicalApplicationAnswers,
    ChildAnswers,
    EmploymentAnswers,
    EssayAnswers,
    PersonAnswers,
    ReferenceAnswers,
)
from app.services.intake import canonical_answers, content_hash, save_working_copy


def _answers() -> CanonicalApplicationAnswers:
    reference = ReferenceAnswers(name="Synthetic Reference", email="ref@example.test", phone="604-555-0101")
    return CanonicalApplicationAnswers(
        applicant=PersonAnswers(
            first_name="Avery",
            last_name="Example",
            birth_date=date(1988, 4, 12),
            phone="604-555-0100",
            email="avery@example.test",
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
        owns_real_estate=False,
        current_landlord=reference,
        essays=EssayAnswers(
            household_introduction="Synthetic household introduction.",
            skills_to_contribute="Synthetic repair skills.",
            previous_coop_experience="Synthetic co-op experience.",
            why_coop="Synthetic interest in shared community work.",
        ),
        applicant_employment=EmploymentAnswers(
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
    assert content_hash(stored) == content_hash({**stored})


def test_canonical_answers_allow_every_child_without_intake_eligibility_block() -> None:
    data = _answers().model_dump()
    data["children"] = data["children"] * 5

    answers = CanonicalApplicationAnswers.model_validate(data)

    assert len(answers.children) == 5


def test_working_copy_does_not_replace_submitted_projection() -> None:
    saved_at = datetime(2026, 8, 23, tzinfo=UTC)
    application = Application(
        primary_email="avery@example.test",
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


def test_opening_participation_and_closed_cycle_snapshot_are_separate() -> None:
    db = _session()
    submitted_at = datetime(2026, 8, 23, tzinfo=UTC)
    application = Application(
        primary_email="avery@example.test",
        applicant_name="Avery Example",
        raw_row={"answer": "submitted"},
        raw_row_hash="content-hash",
        normalized={"applicant_name": "Avery Example"},
        submitted_at=submitted_at,
        declaration_accepted_at=submitted_at,
    )
    opening = Opening(
        title="Synthetic three-bedroom opening",
        unit_size_bedrooms=3,
        housing_charge_cents=120_000,
        move_in_date=date(2026, 10, 1),
        application_deadline=datetime(2026, 7, 31, 23, 59, tzinfo=UTC),
        status=OpeningStatus.OPEN,
    )
    db.add_all([application, opening])
    db.flush()
    participation = ApplicationParticipation(
        application_id=application.id,
        opening_id=opening.id,
        submitted_at=submitted_at,
        declaration_accepted_at=submitted_at,
    )
    db.add(participation)
    db.flush()
    db.add(
        ApplicationCycleSnapshot(
            participation_id=participation.id,
            primary_email=application.primary_email,
            applicant_name=application.applicant_name,
            co_applicant_name=application.co_applicant_name,
            answers=application.raw_row,
            normalized=application.normalized,
            content_hash=application.raw_row_hash,
            submitted_at=submitted_at,
            declaration_accepted_at=submitted_at,
        )
    )
    db.commit()

    assert participation.application_id == application.id
    assert db.query(ApplicationCycleSnapshot).one().answers == {"answer": "submitted"}
