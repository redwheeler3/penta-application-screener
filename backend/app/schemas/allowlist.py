"""Request/response shapes for the access-allowlist admin router."""

from pydantic import EmailStr

from app.db.models import UserRole
from app.schemas.base import RequestModel, ResponseModel


class AllowlistEntryOut(ResponseModel):
    email: str
    role: str


class AllowlistResponse(ResponseModel):
    entries: list[AllowlistEntryOut]


class AllowlistUpsert(RequestModel):
    # EmailStr validates + normalizes shape; the service lowercases for the unique key.
    email: EmailStr
    role: UserRole = UserRole.MEMBER
