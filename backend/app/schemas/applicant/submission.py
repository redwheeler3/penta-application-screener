"""Completeness rules for new submissions, separate from retained and private answers."""

from app.schemas.applicant.answers import (
    AddressAnswers,
    CanonicalApplicationAnswers,
    EmploymentAnswers,
    EmploymentStatus,
    PersonAnswers,
    ReferenceAnswers,
)


def validate_submission_completeness(answers: CanonicalApplicationAnswers) -> None:
    """Require the form's applicable answers without adding eligibility restrictions.

    Canonical answers also describe retained/synthetic data; working copies deliberately
    accept unfinished answers. Only the two submission request contracts call this gate.
    Existing answer models own date, email, income and residence-order validation.
    """
    _person(answers.applicant, "Primary applicant")
    if answers.co_applicant is not None:
        _person(answers.co_applicant, "Co-applicant")
        _required(answers.co_applicant.relationship, "Relationship to applicant")
        if answers.co_applicant_employment is None:
            raise ValueError("Co-applicant employment status is required")
        if answers.co_applicant_income is None:
            raise ValueError("Co-applicant income is required")
        _employment(answers.co_applicant_employment, "Co-applicant")
    for index, child in enumerate(answers.children, start=1):
        _required(child.first_name, f"Child {index} first name")
        _required(child.last_name, f"Child {index} last name")

    _address(answers.current_address, "Current address")
    for index, residence in enumerate(answers.previous_residences, start=1):
        _address(residence.address, f"Previous address {index}")
    if not answers.owns_current_home:
        _reference(answers.current_landlord, "Current landlord")
        if answers.previous_residences:
            _reference(answers.previous_landlord, "Previous landlord")

    for label, value in (
        ("Household introduction", answers.essays.household_introduction),
        ("Skills to contribute", answers.essays.skills_to_contribute),
        ("Previous co-op experience", answers.essays.previous_coop_experience),
        ("Why a co-op", answers.essays.why_coop),
    ):
        _required(value, label)
    _employment(answers.applicant_employment, "Primary applicant")


def _required(value: str | None, label: str) -> None:
    if not value or not value.strip():
        raise ValueError(f"{label} is required")


def _person(person: PersonAnswers, label: str) -> None:
    _required(person.first_name, f"{label} first name")
    _required(person.last_name, f"{label} last name")
    _required(person.phone, f"{label} phone")


def _address(address: AddressAnswers, label: str) -> None:
    for field in ("street", "city", "province_or_state", "postal_or_zip_code", "country"):
        _required(getattr(address, field), f"{label} {field.replace('_', ' ')}")


def _reference(reference: ReferenceAnswers | None, label: str) -> None:
    if reference is None:
        raise ValueError(f"{label} is required")
    _required(reference.name, f"{label} name")
    _required(reference.phone, f"{label} phone")


def _employment(employment: EmploymentAnswers, label: str) -> None:
    if employment.status == EmploymentStatus.UNEMPLOYED:
        return
    _required(employment.job_title, f"{label} job title or type of business")
    _required(employment.company_name, f"{label} employer or business name")
    if employment.status == EmploymentStatus.EMPLOYED:
        _reference(employment.manager, f"{label} manager")
