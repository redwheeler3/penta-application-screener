"""Admin opening-management request and response shapes."""

from datetime import date, datetime

from pydantic import Field, model_validator

from app.db.models import OpeningPhase
from app.schemas.base import RequestModel, ResponseModel


class OpeningWrite(RequestModel):
    unit_size_bedrooms: int = Field(ge=1, le=3)
    housing_charge_cents: int = Field(ge=0)
    application_open_date: date
    application_close_date: date
    move_in_date: date

    @model_validator(mode="after")
    def dates_are_chronological(self) -> "OpeningWrite":
        if self.application_open_date > self.application_close_date:
            raise ValueError("Application open date must be on or before the close date.")
        if self.application_close_date > self.move_in_date:
            raise ValueError("Application close date must be on or before the move-in date.")
        return self


class OpeningDetailsOut(ResponseModel):
    id: int
    unit_size_bedrooms: int
    housing_charge_cents: int
    application_open_date: date
    application_close_date: date
    move_in_date: date


class OpeningOut(OpeningDetailsOut):
    phase: OpeningPhase
    published_at: datetime | None
    submission_count: int
    created_at: datetime
    updated_at: datetime


class OpeningsResponse(ResponseModel):
    openings: list[OpeningOut]
