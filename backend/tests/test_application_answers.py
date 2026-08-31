from app.db.models import Application
from app.services.application_answers import working_answers_for
from tests.applicant.support import legacy_answers


def legacy_application(*, owns_real_estate: bool = False) -> Application:
    row = legacy_answers()
    row["Do you own real estate (land, house, condominium, etc.)?"] = (
        "Yes" if owns_real_estate else "No"
    )
    return Application(
        primary_email="avery@example.com",
        raw_row=row,
        raw_row_hash="legacy",
        normalized={
            "applicant_name": "Avery Ng",
            "co_applicant_name": "Morgan Lee",
            "child_details": [{"first_name": "Casey", "last_name": "Ng", "age": 8}],
            "has_real_estate": owns_real_estate,
            "pets_text": "One cat",
            "applicant_income": 80_000,
            "co_applicant_income": 60_000,
        },
    )


def test_legacy_answers_prefill_known_fields_and_leave_unknowns_blank() -> None:
    answers = working_answers_for(legacy_application())

    assert answers is not None
    assert answers.applicant.first_name == "Avery"
    assert answers.applicant.birth_date == ""
    assert answers.co_applicant is not None
    assert answers.co_applicant.relationship == "Partner"
    assert answers.co_applicant.birth_date == ""
    assert answers.children[0].first_name == "Casey"
    assert answers.children[0].birth_date == ""
    assert answers.current_address.street == "123 Synthetic Street"
    assert answers.lived_at_current_address_two_years is False
    assert answers.owns_current_home is False
    assert answers.owns_other_real_estate is False
    assert answers.essays.household_introduction == "Synthetic household introduction."
    assert answers.pets == "One cat"
    assert answers.applicant_employment.status is None
    assert answers.applicant_employment.job_title == "Teacher"
    assert answers.applicant_employment.manager is not None
    assert answers.applicant_employment.manager.name == "Primary Manager"
    assert answers.applicant_income == 80_000


def test_legacy_combined_property_yes_does_not_invent_which_property_is_owned() -> None:
    answers = working_answers_for(legacy_application(owns_real_estate=True))

    assert answers is not None
    assert answers.owns_current_home is None
    assert answers.owns_other_real_estate is None
