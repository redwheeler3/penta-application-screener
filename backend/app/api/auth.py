from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.api.dependencies import optional_current_user
from app.api.session_cookie import (
    clear_session_cookie,
    session_token,
    set_session_cookie,
)
from app.core.config import Settings, get_settings
from app.core.google_oauth import authorized_google_identity, get_oauth
from app.db.models import PasswordlessIdentityKind, User
from app.db.session import get_db
from app.schemas.auth import CurrentUser, LogoutResponse, MeResponse
from app.services.allowlist import get_entry
from app.services.denied_sign_ins import record_denied_sign_in
from app.services.passwordless_auth import (
    create_browser_session,
    revoke_browser_session,
)
from app.services.users import GoogleIdentityConflict, upsert_google_user

router = APIRouter(prefix="/auth", tags=["auth"])


def serialize_user(user: User) -> CurrentUser:
    return CurrentUser(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        avatar_url=user.avatar_url,
        role=user.role.value,
    )


@router.get("/google/login")
async def google_login(request: Request, remember_device: bool = False):
    request.session["remember_device"] = remember_device
    oauth = get_oauth()
    settings = get_settings()
    return await oauth.google.authorize_redirect(request, settings.google_redirect_uri)


@router.get("/google/callback")
async def google_callback(request: Request, db: Session = Depends(get_db)):
    remember_device = request.session.pop("remember_device", False)
    identity = await authorized_google_identity(request, get_oauth())
    request.session.clear()
    if identity is None:
        return _google_sign_in_denied()

    # Access gate: only allowlisted emails may sign in, and the entry's role is the
    # user's role. A non-listed account is bounced back to the login screen with a
    # flag (an OAuth redirect can't carry a problem+json body) rather than admitted.
    entry = get_entry(db, identity.email)
    if entry is None:
        record_denied_sign_in(
            db,
            google_subject=identity.subject,
            email=identity.email,
            display_name=identity.display_name,
        )
        return _google_sign_in_denied()

    try:
        user = upsert_google_user(
            db,
            google_subject=identity.subject,
            email=identity.email,
            display_name=identity.display_name,
            avatar_url=identity.avatar_url,
            role=entry.role,
        )
    except GoogleIdentityConflict:
        record_denied_sign_in(
            db,
            google_subject=identity.subject,
            email=identity.email,
            display_name=identity.display_name,
        )
        return _google_sign_in_denied()

    issued_session = create_browser_session(
        db,
        identity_kind=PasswordlessIdentityKind.COMMITTEE,
        user_id=user.id,
    )
    db.commit()
    response = RedirectResponse(get_settings().frontend_url)
    set_session_cookie(
        response,
        issued_session.token,
        identity_kind=PasswordlessIdentityKind.COMMITTEE,
        settings=get_settings(),
        persistent=remember_device,
    )
    return response


def _google_sign_in_denied() -> RedirectResponse:
    return RedirectResponse(f"{get_settings().frontend_url}?access=denied")

@router.get("/me", response_model=MeResponse)
def get_current_user(
    user: User | None = Depends(optional_current_user),
    settings: Settings = Depends(get_settings),
) -> MeResponse:
    return MeResponse(
        user=serialize_user(user) if user is not None else None,
        email_sign_in_enabled=settings.email_delivery_enabled,
    )


@router.post("/logout", response_model=LogoutResponse)
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> LogoutResponse:
    token = session_token(request, PasswordlessIdentityKind.COMMITTEE)
    if token is not None:
        revoke_browser_session(db, token)
        db.commit()
    clear_session_cookie(response, PasswordlessIdentityKind.COMMITTEE)
    request.session.clear()
    return LogoutResponse(ok=True)
