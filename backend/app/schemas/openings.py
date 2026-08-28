"""Admin opening-management request and response shapes."""

from datetime import date, datetime

from pydantic import Field, model_validator

from app.db.models import OpeningPhase
from app.schemas.base import RequestModel, ResponseModel


class OpeningCreate(RequestModel):
    unit_size_bedrooms: int = Field(ge=1, le=3)
    housing_charge_cents: int = Field(ge=0)
    application_close_date: date
    move_in_date: date

    @model_validator(mode="after")
    def dates_are_chronological(self) -> "OpeningCreate":
        if self.application_close_date > self.move_in_date:
            raise ValueError("Application close date must be on or before the move-in date.")
        return self


class OpeningWrite(OpeningCreate):
    application_open_date: date

    @model_validator(mode="after")
    def open_date_precedes_close_date(self) -> "OpeningWrite":
        if self.application_open_date > self.application_close_date:
            raise ValueError("Application open date must be on or before the close date.")
        return self


class OpeningCreateConfirmation(OpeningCreate):
    expected_audience_count: int = Field(ge=0)


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
    selected_application_id: int | None
    selected_applicant_name: str | None
    no_household_selected: bool
    decision_permanent: bool
    needs_decision: bool
    created_at: datetime
    updated_at: datetime


class OpeningsResponse(ResponseModel):
    openings: list[OpeningOut]


class OpeningNotificationVariantOut(ResponseModel):
    kind: str
    recipient_count: int


class SocketLabsUsageOut(ResponseModel):
    available: bool
    retrieved_at: datetime | None = None
    billing_period_start: datetime | None = None
    billing_period_end: datetime | None = None
    messages_used: int | None = None
    message_allowance: int | None = None
    messages_used_percent: float | None = None
    allow_overages: bool | None = None
    projected_messages_used: int | None = None


class OpeningPreviewOut(ResponseModel):
    audience_count: int
    subscriber_only_count: int
    application_only_count: int
    overlap_count: int
    variants: list[OpeningNotificationVariantOut]
    socketlabs: SocketLabsUsageOut


class OpeningCreatedOut(OpeningsResponse):
    queued_notification_count: int


class OpeningSelectionRequest(RequestModel):
    application_id: int = Field(gt=0)


class OpeningSelectionCandidateOut(ResponseModel):
    application_id: int
    applicant_name: str | None
    primary_email: str


class OpeningSelectionOut(ResponseModel):
    opening_id: int
    phase: OpeningPhase
    selected_application_id: int | None
    selected_applicant_name: str | None
    no_household_selected: bool
    decision_permanent: bool
    active_participant_count: int
    candidates: list[OpeningSelectionCandidateOut]
