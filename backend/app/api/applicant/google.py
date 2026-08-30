"""Identity-only Google access for applicant applications."""

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.api.session_cookie import session_token, set_session_cookie
from app.core.config import get_settings
from app.core.google_oauth import authorized_google_identity, get_oauth
from app.db.models import PasswordlessIdentityKind
from app.db.session import get_db
from app.services.applicant_auth import authenticate_applicant
from app.services.applicant_google_auth import (
    ApplicantGoogleIdentityConflict,
    NewApplicationsUnavailable,
    claim_or_create_google_application,
)
from app.services.passwordless_auth import (
    create_browser_session,
    revoke_browser_session,
)

router = APIRouter()


@router.get("/auth/google/login")
async def applicant_google_login(request: Request, remember_device: bool = False):
    request.session["applicant_remember_device"] = remember_device
    return await get_oauth().google.authorize_redirect(
        request,
        get_settings().google_applicant_redirect_uri,
    )


@router.get("/auth/google/callback")
async def applicant_google_callback(
    request: Request,
    db: Session = Depends(get_db),
):
    remember_device = request.session.pop("applicant_remember_device", False)
    identity = await authorized_google_identity(request, get_oauth())
    request.session.clear()
    if identity is None:
        return _applicant_redirect("denied")

    current_token = session_token(request, PasswordlessIdentityKind.APPLICANT)
    current = (
        authenticate_applicant(db, current_token)
        if current_token is not None
        else None
    )

    try:
        application = claim_or_create_google_application(
            db,
            google_subject=identity.subject,
            email=identity.email,
        )
    except ApplicantGoogleIdentityConflict:
        db.rollback()
        return _applicant_redirect("identity_conflict")
    except NewApplicationsUnavailable:
        db.rollback()
        return _applicant_redirect("applications_closed")

    if current_token is not None:
        if current is not None and current.application.id != application.id:
            db.rollback()
            return _applicant_redirect("session_conflict")
        revoke_browser_session(db, current_token)

    issued_session = create_browser_session(
        db,
        identity_kind=PasswordlessIdentityKind.APPLICANT,
        application_id=application.id,
    )
    db.commit()
    response = _applicant_redirect()
    set_session_cookie(
        response,
        issued_session.token,
        identity_kind=PasswordlessIdentityKind.APPLICANT,
        settings=get_settings(),
        persistent=remember_device,
    )
    return response


def _applicant_redirect(result: str | None = None) -> RedirectResponse:
    target = get_settings().applicant_frontend_url
    if result is not None:
        parts = urlsplit(target)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        query["google_access"] = result
        target = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
    return RedirectResponse(target)
