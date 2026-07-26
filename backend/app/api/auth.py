from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

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
    return await oauth.google.authorize_redirect(
        request,
        settings.google_redirect_uri,
        access_type="offline",
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
