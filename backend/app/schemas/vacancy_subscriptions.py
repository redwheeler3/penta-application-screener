"""Public and administrator vacancy-notification contracts."""

from datetime import datetime
from typing import Annotated

from pydantic import EmailStr, Field, StringConstraints

from app.schemas.base import RequestModel, ResponseModel

RequestSource = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=2, max_length=120),
]


class VacancySubscriptionWrite(RequestModel):
    email: EmailStr
    unit_sizes: set[int] = Field(min_length=1)


class VacancySubscriptionPublicWrite(VacancySubscriptionWrite):
    consent_version: str = Field(min_length=1, max_length=30)


class VacancySubscriptionAdminWrite(VacancySubscriptionWrite):
    source: RequestSource


class VacancySubscriptionLookup(RequestModel):
    email: EmailStr


class VacancySubscriptionDelete(VacancySubscriptionLookup):
    source: RequestSource


class VacancySubscriptionPublicOut(ResponseModel):
    saved: bool = True


class VacancySubscriptionOut(ResponseModel):
    email: str
    unit_sizes: list[int]
    first_consented_at: datetime
    consented_at: datetime
    source: str


class VacancySubscriptionLookupOut(ResponseModel):
    subscription: VacancySubscriptionOut | None


class VacancySubscriptionMonthOut(ResponseModel):
    month: str
    count: int


class VacancySubscriptionReportOut(ResponseModel):
    total: int
    one_bedroom: int
    two_bedroom: int
    three_bedroom: int
    months: list[VacancySubscriptionMonthOut]
