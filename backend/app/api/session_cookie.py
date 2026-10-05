"""The HTTP-only boundary for passwordless browser-session credentials."""

from fastapi import Request, Response
from starlette.middleware.sessions import SessionMiddleware

from app.core.config import Settings
from app.core.problems import Problem
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
    persistent: bool = False,
) -> None:
    cookie_options = {}
    if persistent:
        cookie_options["max_age"] = settings.session_absolute_days * 24 * 60 * 60
    response.set_cookie(
        SESSION_COOKIE_NAMES[identity_kind],
        token,
        secure=settings.passwordless_cookie_secure(identity_kind.value),
        httponly=True,
        samesite="lax",
        path="/",
        **cookie_options,
    )


def check_request_identity(request: Request, kind: PasswordlessIdentityKind,
                           actual_id: int | None, *, required: bool = False) -> None:
    """Bind browser work to its displayed identity, before any protected action.

    Non-browser manual clients may omit the header. Browser callers supply an ID
    (or explicit signed-out state); bootstrap reads deliberately omit it.
    """
    expected = request.headers.get("x-penta-identity")
    if expected is None:
        if required and request.headers.get("sec-fetch-site") is not None:
            raise Problem("session_changed", detail="Reload your session before continuing.")
        return
    actual = f"{kind.value}:{actual_id if actual_id is not None else 'none'}"
    if expected != actual:
        raise Problem("session_changed", detail="Your session changed. This action was not applied.")


class OAuthStateMiddleware(SessionMiddleware):
    """Only OAuth transitions may read/write Authlib's short-lived state cookie."""

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"] not in {
            "/auth/google/login", "/auth/google/callback",
            "/applicant/auth/google/login", "/applicant/auth/google/callback",
        }:
            scope["session"] = {}
            await self.app(scope, receive, send)
        else:
            await super().__call__(scope, receive, send)
