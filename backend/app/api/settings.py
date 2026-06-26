from fastapi import APIRouter, Depends
from googleapiclient.errors import HttpError
from sqlalchemy.orm import Session

from app.api.dependencies import require_current_user
from app.api.problems import Problem
from app.core.config import get_settings
from app.db.session import get_db
from app.db.models import User
from app.schemas.settings import AppSettings, SettingsResponse, google_sheet_url_from_id
from app.services.google_credentials import get_google_token
from app.services.google_sheets import fetch_sheet_title
from app.services.settings import get_app_settings, save_app_settings

router = APIRouter(prefix="/settings", tags=["settings"])


def build_settings_response(db: Session, user: User, settings: AppSettings) -> SettingsResponse:
    sheet_title: str | None = None
    if settings.google_sheet_id:
        token = get_google_token(db, user_id=user.id)
        if token is not None:
            try:
                sheet_title = fetch_sheet_title(
                    sheet_id=settings.google_sheet_id,
                    token=token,
                    settings=get_settings(),
                )
            except HttpError:
                sheet_title = None

    return SettingsResponse(
        settings=settings,
        google_sheet_url=google_sheet_url_from_id(settings.google_sheet_id),
        google_sheet_title=sheet_title,
    )


@router.get("", response_model=SettingsResponse)
def read_settings(
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> SettingsResponse:
    return build_settings_response(db, user, get_app_settings(db))


@router.put("", response_model=SettingsResponse)
def update_settings(
    settings: AppSettings,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> SettingsResponse:
    if settings.income_max < settings.income_min:
        raise Problem(
            "invalid_settings",
            detail="Income maximum must be greater than or equal to income minimum.",
        )

    return build_settings_response(db, user, save_app_settings(db, settings))
