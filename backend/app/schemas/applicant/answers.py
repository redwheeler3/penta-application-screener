"""Canonical built-in application answers, independent of form labels or UI layout."""

from datetime import date
from enum import StrEnum

from pydantic import EmailStr, Field, HttpUrl, model_validator

from app.schemas.base import BridgeModel


class PersonAnswers(BridgeModel):
    first_name: str
    last_name: str
    birth_date: date
    phone: str
    email: EmailStr


class CoApplicantAnswers(PersonAnswers):
    relationship: str


class ChildAnswers(BridgeModel):
    first_name: str
    last_name: str
    birth_date: date


class AddressAnswers(BridgeModel):
    street: str
    street_2: str | None = None
    city: str
    province_or_state: str
    postal_or_zip_code: str
    country: str


class ReferenceAnswers(BridgeModel):
    name: str
    email: EmailStr
    phone: str


class EssayAnswers(BridgeModel):
    household_introduction: str
    skills_to_contribute: str
    previous_coop_experience: str
    why_coop: str
    additional_information: str = ""


class EmploymentStatus(StrEnum):
    EMPLOYED = "employed"
    SELF_EMPLOYED = "self_employed"
    UNEMPLOYED = "unemployed"


class EmploymentAnswers(BridgeModel):
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


class WorkingPersonAnswers(BridgeModel):
    first_name: str = ""
    last_name: str = ""
    birth_date: str = ""
    phone: str = ""
    email: str = ""


class WorkingCoApplicantAnswers(WorkingPersonAnswers):
    relationship: str = ""


class WorkingChildAnswers(BridgeModel):
    first_name: str = ""
    last_name: str = ""
    birth_date: str = ""


class WorkingReferenceAnswers(BridgeModel):
    name: str = ""
    email: str = ""
    phone: str = ""


class WorkingEmploymentAnswers(BridgeModel):
    status: EmploymentStatus | None = None
    job_title: str | None = None
    company_name: str | None = None
    start_date: str | None = None
    manager: WorkingReferenceAnswers | None = None


class WorkingApplicationAnswers(BridgeModel):
    """A typed but intentionally incomplete private working copy."""

    applicant: WorkingPersonAnswers
    co_applicant: WorkingCoApplicantAnswers | None = None
    children: list[WorkingChildAnswers] = Field(default_factory=list)
    current_address: AddressAnswers
    lived_at_current_address_two_years: bool | None = None
    owns_current_home: bool | None = None
    owns_other_real_estate: bool | None = None
    current_landlord: WorkingReferenceAnswers | None = None
    previous_landlord: WorkingReferenceAnswers | None = None
    essays: EssayAnswers
    pets: str | None = None
    household_photo_link: str | None = None
    applicant_employment: WorkingEmploymentAnswers
    co_applicant_employment: WorkingEmploymentAnswers | None = None
    applicant_income: int | None = Field(default=None, ge=0)
    co_applicant_income: int | None = Field(default=None, ge=0)


class CanonicalApplicationAnswers(BridgeModel):
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
    household_photo_link: HttpUrl | None = None
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
