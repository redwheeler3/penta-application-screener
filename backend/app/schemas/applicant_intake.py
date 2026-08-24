"""Wire contracts for private applicant drafts, access links, and applications."""

from typing import Literal

from pydantic import EmailStr, Field

from app.db.models import ApplicantDraftIntent, MagicLinkPurpose
from app.schemas.base import RequestModel, ResponseModel
from app.schemas.intake import CanonicalApplicationAnswers, WorkingApplicationAnswers


class PendingDraftRequest(RequestModel):
    answers: WorkingApplicationAnswers
    intent: ApplicantDraftIntent
    draft_token: str | None = Field(default=None, min_length=32, max_length=500)


class PendingDraftResponse(ResponseModel):
    draft_token: str
    email_sent: bool
    retry_after_seconds: int


class RequestAccessLinkRequest(RequestModel):
    answers: WorkingApplicationAnswers


class RequestAccessLinkResponse(ResponseModel):
    accepted: bool = True
    current_answers_saved: bool


class AccessLinkRequest(RequestModel):
    token: str = Field(min_length=32, max_length=500)


class OpenAccessLinkRequest(AccessLinkRequest):
    switch_current: bool = False
    remember_device: bool = False


class AccessLinkResponse(ResponseModel):
    state: Literal[
        "valid", "expired", "used", "replaced", "invalid", "abandoned", "email_in_use"
    ]
    purpose: MagicLinkPurpose | None = None
    current_email: str | None = None
    link_email: str | None = None
    application_email: str | None = None
    switch_required: bool = False
    application_id: int | None = None
    pending_intent: ApplicantDraftIntent | None = None


class RegenerateAccessLinkResponse(ResponseModel):
    accepted: bool = True
    email_sent: bool
    retry_after_seconds: int


class ApplicantApplicationResponse(ResponseModel):
    application_id: int
    primary_email: str
    pending_email_change: str | None = None
    answers: WorkingApplicationAnswers | None = None
    submitted: bool
    has_unsubmitted_changes: bool


class SaveApplicationRequest(RequestModel):
    answers: WorkingApplicationAnswers


class EmailChangeRequest(RequestModel):
    new_email: EmailStr


class EmailChangeResponse(ResponseModel):
    email_sent: bool
    retry_after_seconds: int
    pending_email: str | None


class SubmitApplicationRequest(RequestModel):
    answers: CanonicalApplicationAnswers
    declaration_accepted: bool = False
