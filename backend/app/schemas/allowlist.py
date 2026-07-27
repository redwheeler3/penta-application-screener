"""Request/response shapes for the access-allowlist admin router."""

from datetime import datetime

from pydantic import EmailStr

from app.db.models import UserRole
from app.schemas.base import RequestModel, ResponseModel


class AllowlistEntryOut(ResponseModel):
    email: str
    role: str
    display_name: str | None = None
    first_signed_in_at: datetime | None = None
    last_signed_in_at: datetime | None = None
    sign_in_count: int = 0


class AllowlistResponse(ResponseModel):
    entries: list[AllowlistEntryOut]


class DeniedSignInAttemptOut(ResponseModel):
    display_name: str
    email: str
    first_denied_at: datetime
    last_denied_at: datetime
    count: int


class DeniedSignInAttemptsResponse(ResponseModel):
    attempts: list[DeniedSignInAttemptOut]


class AllowlistUpsert(RequestModel):
    # EmailStr validates + normalizes shape; the service lowercases for the unique key.
    email: EmailStr
    role: UserRole = UserRole.MEMBER
