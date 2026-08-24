from pydantic import Field

from app.schemas.auth import CurrentUser
from app.schemas.base import RequestModel, ResponseModel


class MagicLinkRequest(RequestModel):
    email: str = Field(min_length=3, max_length=320)


class MagicLinkConsumeRequest(RequestModel):
    token: str = Field(min_length=32, max_length=500)


class MagicLinkRequestResponse(ResponseModel):
    accepted: bool = True
    message: str = "If this address has access, a sign-in email is on its way."


class CommitteeSignInResponse(ResponseModel):
    user: CurrentUser


class ApplicantSignInResponse(ResponseModel):
    application_id: int


class ApplicantMeResponse(ResponseModel):
    application_id: int | None = None
