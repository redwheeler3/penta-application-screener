"""Canonical built-in application answers, independent of form labels or UI layout."""

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator


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


class EmploymentStatus(StrEnum):
    EMPLOYED = "employed"
    SELF_EMPLOYED = "self_employed"
    UNEMPLOYED = "unemployed"


class EmploymentAnswers(BaseModel):
    status: EmploymentStatus
    job_title: str | None = None
    company_name: str | None = None
    start_date: date | None = None
    manager: ReferenceAnswers | None = None

    @model_validator(mode="after")
    def validate_details_for_status(self) -> "EmploymentAnswers":
        if self.status == EmploymentStatus.UNEMPLOYED:
            self.job_title = None
            self.company_name = None
            self.start_date = None
            self.manager = None
            return self
        if not self.job_title or not self.company_name or self.start_date is None:
            raise ValueError("employment details are required for this status")
        if self.status == EmploymentStatus.EMPLOYED and self.manager is None:
            raise ValueError("manager details are required for employed applicants")
        if self.status == EmploymentStatus.SELF_EMPLOYED:
            self.manager = None
        return self


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
    owns_current_home: bool
    owns_other_real_estate: bool
    current_landlord: ReferenceAnswers | None = None
    previous_landlord: ReferenceAnswers | None = None
    essays: EssayAnswers
    pets: str | None = None
    applicant_employment: EmploymentAnswers
    co_applicant_employment: EmploymentAnswers | None = None
    applicant_income: int = Field(ge=0)
    co_applicant_income: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_housing_references(self) -> "CanonicalApplicationAnswers":
        if not self.owns_current_home and self.current_landlord is None:
            raise ValueError("a current landlord is required for renters")
        if (
            not self.owns_current_home
            and not self.lived_at_current_address_two_years
            and self.previous_landlord is None
        ):
            raise ValueError("a previous housing reference is required")
        return self

    @property
    def household_income(self) -> int:
        co_applicant_income = (
            self.co_applicant_income if self.co_applicant is not None else None
        )
        return self.applicant_income + (co_applicant_income or 0)

    @property
    def owns_real_estate(self) -> bool:
        return self.owns_current_home or self.owns_other_real_estate
