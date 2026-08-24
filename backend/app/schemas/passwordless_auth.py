from typing import Literal

from pydantic import Field

from app.schemas.auth import CurrentUser
from app.schemas.base import RequestModel, ResponseModel


class MagicLinkRequest(RequestModel):
    email: str = Field(min_length=3, max_length=320)
    remember_device: bool = False


class MagicLinkConsumeRequest(RequestModel):
    token: str = Field(min_length=32, max_length=500)
    switch_current: bool = False


class MagicLinkRequestResponse(ResponseModel):
    accepted: bool = True
    message: str = "If this address has access, a sign-in email is on its way."


class CommitteeSignInResponse(ResponseModel):
    user: CurrentUser


class CommitteeLinkInspectionResponse(ResponseModel):
    state: Literal["valid", "expired", "used", "replaced", "invalid"]
    current_user: CurrentUser | None = None
    link_email: str | None = None
    switch_required: bool = False


class ApplicantMeResponse(ResponseModel):
    application_id: int | None = None
