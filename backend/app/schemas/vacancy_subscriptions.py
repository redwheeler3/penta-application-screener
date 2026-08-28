"""Public and administrator vacancy-notification contracts."""

from datetime import datetime

from pydantic import EmailStr, Field

from app.schemas.base import RequestModel, ResponseModel


class VacancySubscriptionWrite(RequestModel):
    email: EmailStr
    unit_sizes: set[int] = Field(min_length=1)


class VacancySubscriptionAdminWrite(VacancySubscriptionWrite):
    source: str = Field(min_length=2, max_length=120)


class VacancySubscriptionLookup(RequestModel):
    email: EmailStr


class VacancySubscriptionDelete(VacancySubscriptionLookup):
    source: str = Field(min_length=2, max_length=120)


class VacancySubscriptionPublicOut(ResponseModel):
    saved: bool = True


class VacancySubscriptionOut(ResponseModel):
    email: str
    unit_sizes: list[int]
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
