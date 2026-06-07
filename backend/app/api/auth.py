from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.google_oauth import get_oauth
from app.db.models import User
from app.db.session import get_db
from app.services.users import upsert_google_user

router = APIRouter(prefix="/auth", tags=["auth"])


def serialize_user(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "email": user.email,
        "displayName": user.display_name,
        "avatarUrl": user.avatar_url,
        "role": user.role.value,
    }


@router.get("/google/login")
async def google_login(request: Request):
    oauth = get_oauth()
    settings = get_settings()
    return await oauth.google.authorize_redirect(request, settings.google_redirect_uri)


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
        raise HTTPException(status_code=400, detail="Google did not return required user identity fields.")

    user = upsert_google_user(
        db,
        google_subject=str(google_subject),
        email=str(email),
        display_name=str(display_name),
        avatar_url=user_info.get("picture"),
    )
    request.session["user_id"] = user.id
    return RedirectResponse(get_settings().frontend_url)


@router.get("/me")
def get_current_user(request: Request, db: Session = Depends(get_db)):
    user_id = request.session.get("user_id")
    if user_id is None:
        return {"user": None}

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        request.session.clear()
        return {"user": None}

    return {"user": serialize_user(user)}


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return {"ok": True}

