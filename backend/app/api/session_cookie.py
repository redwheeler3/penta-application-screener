"""The HTTP-only boundary for passwordless browser-session credentials."""

from fastapi import Request, Response

from app.core.config import Settings
from app.db.models import PasswordlessIdentityKind

SESSION_COOKIE_NAMES = {
    PasswordlessIdentityKind.APPLICANT: "penta_applicant_session",
    PasswordlessIdentityKind.COMMITTEE: "penta_committee_session",
}


def session_token(
    request: Request, identity_kind: PasswordlessIdentityKind
) -> str | None:
    return request.cookies.get(SESSION_COOKIE_NAMES[identity_kind])


def set_session_cookie(
    response: Response,
    token: str,
    *,
    identity_kind: PasswordlessIdentityKind,
    settings: Settings,
) -> None:
    response.set_cookie(
        SESSION_COOKIE_NAMES[identity_kind],
        token,
        max_age=settings.session_absolute_days * 24 * 60 * 60,
        secure=settings.passwordless_cookie_secure(identity_kind.value),
        httponly=True,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(
    response: Response, identity_kind: PasswordlessIdentityKind
) -> None:
    response.delete_cookie(
        SESSION_COOKIE_NAMES[identity_kind],
        httponly=True,
        samesite="lax",
        path="/",
    )
