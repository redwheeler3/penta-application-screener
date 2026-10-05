from fastapi import Depends, Request, Response
from sqlalchemy.orm import Session

from app.api.session_cookie import check_request_identity, session_token
from app.core.problems import Problem
from app.db.models import Application, PasswordlessIdentityKind
from app.db.session import get_db
from app.services.auth.applicant import authenticate_applicant


def optional_current_application(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> Application | None:
    token = session_token(request, PasswordlessIdentityKind.APPLICANT)
    if token is None:
        check_request_identity(request, PasswordlessIdentityKind.APPLICANT, None)
        return None
    authentication = authenticate_applicant(db, token)
    if authentication is None:
        check_request_identity(request, PasswordlessIdentityKind.APPLICANT, None)
        return None
    request.state.passwordless_session = authentication.browser_session
    check_request_identity(request, PasswordlessIdentityKind.APPLICANT, authentication.application.id)
    return authentication.application


def require_current_application(
    request: Request,
    application: Application | None = Depends(optional_current_application),
) -> Application:
    if application is None:
        raise Problem("unauthorized", detail="Application access required.")
    # The initial application GET is also the one-response applicant bootstrap.
    bootstrap = request.method == "GET" and request.url.path == "/applicant/application"
    check_request_identity(request, PasswordlessIdentityKind.APPLICANT, application.id, required=not bootstrap)
    return application
