from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.api.dependencies import require_admin
from app.api.problems import Problem
from app.core.config import get_settings
from app.core.google_oauth import get_oauth
from app.db.models import User
from app.db.session import get_db
from app.schemas.auth import CurrentUser, LogoutResponse, MeResponse
from app.services.allowlist import get_entry
from app.services.google_credentials import save_google_token
from app.services.users import upsert_google_user

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
async def google_login(request: Request):
    oauth = get_oauth()
    settings = get_settings()
    # Normal member/admin login: identity + the current login scopes. Clear any stale
    # connect-sheet intent so a plain login never accidentally re-links the sheet.
    request.session.pop("oauth_intent", None)
    return await oauth.google.authorize_redirect(
        request,
        settings.google_redirect_uri,
        access_type="offline",
        prompt="consent",
    )


@router.get("/google/connect-sheet")
async def google_connect_sheet(request: Request, admin: User = Depends(require_admin)):
    """Incremental authorization (M18): an admin re-consents to add the drive.file scope to
    their stored token, so their OFFLINE token (with refresh) can durably read the sheet they
    pick. Reuses the normal callback (no extra redirect URI to register) via a session intent
    flag; the callback stores the enriched token and marks this admin the designated reader.
    ``include_granted_scopes`` keeps their already-granted identity scopes."""
    oauth = get_oauth()
    settings = get_settings()
    request.session["oauth_intent"] = "connect_sheet"
    return await oauth.google.authorize_redirect(
        request,
        settings.google_redirect_uri,
        scope=settings.google_sheet_reader_scopes,
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )


@router.get("/google/callback")
async def google_callback(request: Request, db: Session = Depends(get_db)):
    oauth = get_oauth()
    token = await oauth.google.authorize_access_token(request)
    user_info = token.get("userinfo")

    if not user_info:
        user_info = await oauth.google.userinfo(token=token)

    google_subject = user_info.get("sub")
    email = user_info.get("email")
    display_name = user_info.get("name") or email

    if not google_subject or not email:
        raise Problem(
            "validation_error",
            detail="Google did not return required user identity fields.",
        )

    # Access gate: only allowlisted emails may sign in, and the entry's role is the
    # user's role. A non-listed account is bounced back to the login screen with a
    # flag (an OAuth redirect can't carry a problem+json body) rather than admitted.
    entry = get_entry(db, str(email))
    if entry is None:
        return RedirectResponse(f"{get_settings().frontend_url}?access=denied")

    user = upsert_google_user(
        db,
        google_subject=str(google_subject),
        email=str(email),
        display_name=str(display_name),
        avatar_url=user_info.get("picture"),
        role=entry.role,
    )
    save_google_token(db, user_id=user.id, token=dict(token))
    request.session["user_id"] = user.id

    # If this was the admin connect-sheet incremental grant (M18), the token just stored now
    # carries drive.file — send them back to Settings to finish picking the sheet, not the
    # home page. One-shot: clear the intent so it can't affect a later plain login.
    if request.session.pop("oauth_intent", None) == "connect_sheet":
        return RedirectResponse(f"{get_settings().frontend_url}?connect=sheet")
    return RedirectResponse(get_settings().frontend_url)


@router.get("/me", response_model=MeResponse)
def get_current_user(request: Request, db: Session = Depends(get_db)) -> MeResponse:
    user_id = request.session.get("user_id")
    if user_id is None:
        return MeResponse(user=None)

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        request.session.clear()
        return MeResponse(user=None)

    return MeResponse(user=serialize_user(user))


@router.post("/logout", response_model=LogoutResponse)
def logout(request: Request) -> LogoutResponse:
    request.session.clear()
    return LogoutResponse(ok=True)
