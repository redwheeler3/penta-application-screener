"""Canonical built-in application answers, independent of form labels or UI layout."""

from datetime import date

from pydantic import BaseModel, Field


class PersonAnswers(BaseModel):
    first_name: str
    last_name: str
    birth_date: date
    phone: str
    email: str


class CoApplicantAnswers(PersonAnswers):
    relationship: str


class ChildAnswers(BaseModel):
    first_name: str
    last_name: str
    birth_date: date


class AddressAnswers(BaseModel):
    street: str
    street_2: str | None = None
    city: str
    province_or_state: str
    postal_or_zip_code: str
    country: str


class ReferenceAnswers(BaseModel):
    name: str
    email: str
    phone: str


class EssayAnswers(BaseModel):
    household_introduction: str
    skills_to_contribute: str
    previous_coop_experience: str
    why_coop: str


class EmploymentAnswers(BaseModel):
    job_title: str
    company_name: str
    start_date: date
    manager: ReferenceAnswers


class CanonicalApplicationAnswers(BaseModel):
    """The durable answer document used by working copies and submissions.

    Required-vs-optional structure mirrors the existing form. Cross-field completeness
    (for example, an optional co-applicant being either wholly present or absent) belongs
    to the submission validator rather than weakening these nested types.
    """

    applicant: PersonAnswers
    co_applicant: CoApplicantAnswers | None = None
    children: list[ChildAnswers] = Field(default_factory=list)
    current_address: AddressAnswers
    lived_at_current_address_two_years: bool
    owns_real_estate: bool
    current_landlord: ReferenceAnswers
    previous_landlord: ReferenceAnswers | None = None
    essays: EssayAnswers
    pets: str | None = None
    applicant_employment: EmploymentAnswers
    co_applicant_employment: EmploymentAnswers | None = None
    applicant_income: int = Field(ge=0)
    co_applicant_income: int | None = Field(default=None, ge=0)

    @property
    def household_income(self) -> int:
        return self.applicant_income + (self.co_applicant_income or 0)
