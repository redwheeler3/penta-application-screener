"""Wire contracts for private applicant drafts, access links, and applications."""

from datetime import datetime
from typing import Literal

from pydantic import EmailStr, Field

from app.db.models import ApplicantDraftIntent, MagicLinkPurpose, OpeningPhase
from app.schemas.applicant.answers import (
    CanonicalApplicationAnswers,
    WorkingApplicationAnswers,
)
from app.schemas.base import RequestModel, ResponseModel
from app.schemas.openings import OpeningDetailsOut

EmailSendStatus = Literal["sent", "recent", "failed"]


class PendingDraftRequest(RequestModel):
    answers: WorkingApplicationAnswers
    opening_ids: list[int] = Field(default_factory=list, max_length=20)
    intent: ApplicantDraftIntent
    draft_token: str | None = Field(default=None, min_length=32, max_length=500)


class PendingDraftResponse(ResponseModel):
    draft_token: str
    email_sent: bool
    retry_after_seconds: int
    email_status: EmailSendStatus


class RequestAccessLinkRequest(RequestModel):
    answers: WorkingApplicationAnswers
    opening_ids: list[int] = Field(default_factory=list, max_length=20)
    base_revision: int | None = Field(default=None, ge=1)


class RequestAccessLinkResponse(ResponseModel):
    accepted: bool = True
    current_answers_saved: bool
    email_status: EmailSendStatus


class AccessLinkRequest(RequestModel):
    token: str = Field(min_length=32, max_length=500)


class OpenAccessLinkRequest(AccessLinkRequest):
    switch_current: bool = False
    remember_device: bool = False


class PendingCopyOut(ResponseModel):
    saved_answers: WorkingApplicationAnswers
    saved_opening_ids: list[int]
    guest_answers: WorkingApplicationAnswers
    guest_opening_ids: list[int]


class AccessLinkResponse(ResponseModel):
    state: Literal[
        "valid",
        "expired",
        "used",
        "replaced",
        "invalid",
        "abandoned",
        "unavailable",
        "email_in_use",
    ]
    purpose: MagicLinkPurpose | None = None
    current_email: str | None = None
    link_email: str | None = None
    application_email: str | None = None
    switch_required: bool = False
    application_id: int | None = None
    pending_intent: ApplicantDraftIntent | None = None
    pending_copy: PendingCopyOut | None = None
    google_disconnected: bool = False


class RegenerateAccessLinkResponse(ResponseModel):
    accepted: bool = True
    target_available: bool = True
    email_sent: bool
    retry_after_seconds: int
    email_status: EmailSendStatus


class ApplicantOpeningOut(OpeningDetailsOut):
    phase: OpeningPhase
    selected: bool
    participating: bool
    has_participated: bool
    can_select: bool
    can_withdraw: bool


class ApplicantApplicationResponse(ResponseModel):
    application_id: int
    primary_email: str
    google_sign_in_linked: bool
    pending_email_change: str | None = None
    answers: WorkingApplicationAnswers | None = None
    working_saved_at: datetime | None = None
    working_revision: int
    submitted: bool
    can_edit: bool
    openings: list[ApplicantOpeningOut]


class ApplicantOpeningsResponse(ResponseModel):
    can_start_application: bool
    openings: list[ApplicantOpeningOut]


class SaveApplicationRequest(RequestModel):
    answers: WorkingApplicationAnswers
    opening_ids: list[int] = Field(default_factory=list, max_length=20)
    base_revision: int = Field(ge=1)


class EmailChangeRequest(RequestModel):
    new_email: EmailStr


class EmailChangeResponse(ResponseModel):
    email_sent: bool
    retry_after_seconds: int
    pending_email: str | None
    email_status: EmailSendStatus


class SubmitApplicationRequest(RequestModel):
    answers: CanonicalApplicationAnswers
    opening_ids: list[int] = Field(max_length=20)
    declaration_accepted: bool = False
    base_revision: int | None = Field(default=None, ge=1)


class GuestSubmitApplicationRequest(SubmitApplicationRequest):
    draft_token: str | None = Field(default=None, min_length=32, max_length=500)


class GuestSubmitApplicationResponse(ResponseModel):
    submitted: bool = True


class GuestSubmissionCheckRequest(RequestModel):
    answers: WorkingApplicationAnswers
    opening_ids: list[int] = Field(default_factory=list, max_length=20)


class GuestSubmissionCheckResponse(ResponseModel):
    can_submit: bool
    email_sent: bool = False
    email_status: EmailSendStatus | None = None


class PendingCopyResponse(ResponseModel):
    pending_copy: PendingCopyOut | None = None


class ReconcilePendingCopyRequest(RequestModel):
    choice: Literal["saved", "guest"]


class WithdrawApplicationResponse(ResponseModel):
    withdrawn: bool = True
