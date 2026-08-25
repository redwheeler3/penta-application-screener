from fastapi import Depends, Request, Response
from sqlalchemy.orm import Session

from app.api.problems import Problem
from app.api.session_cookie import clear_session_cookie, session_token
from app.db.models import Application, PasswordlessIdentityKind
from app.db.session import get_db
from app.services.applicant_auth import authenticate_applicant
from app.services.passwordless_auth import recently_authenticated


def optional_current_application(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> Application | None:
    token = session_token(request, PasswordlessIdentityKind.APPLICANT)
    if token is None:
        return None
    authentication = authenticate_applicant(db, token)
    if authentication is None:
        clear_session_cookie(response, PasswordlessIdentityKind.APPLICANT)
        return None
    request.state.passwordless_session = authentication.browser_session
    return authentication.application


def require_current_application(
    application: Application | None = Depends(optional_current_application),
) -> Application:
    if application is None:
        raise Problem("unauthorized", detail="Application access required.")
    return application


def require_recent_applicant(
    request: Request,
    application: Application = Depends(require_current_application),
) -> Application:
    """Require a sign-in within the sensitive-action window."""
    browser_session = getattr(request.state, "passwordless_session", None)
    if browser_session is None or not recently_authenticated(browser_session):
        raise Problem(
            "recent_authentication_required",
            detail="Sign in again before continuing.",
        )
    return application
