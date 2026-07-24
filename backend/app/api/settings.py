from fastapi import APIRouter, Depends
from googleapiclient.errors import HttpError
from sqlalchemy.orm import Session

from app.api.dependencies import require_current_user
from app.api.problems import Problem
from app.core.config import get_settings
from app.db.models import User
from app.db.session import get_db
from app.schemas.settings import (
    AppSettings,
    EligibilityRules,
    EligibilityRulesResponse,
    SettingsResponse,
    google_sheet_url_from_id,
)
from app.services.google_credentials import get_google_token
from app.services.google_sheets import fetch_sheet_title
from app.services.rules import member_rules, save_member_rules
from app.services.settings import get_app_settings, save_app_settings

router = APIRouter(prefix="/settings", tags=["settings"])

# The per-member eligibility rules live under their own path: they are a member-scoped
# resource (each member reads/edits their own), whereas /settings is the shared infra config.
rules_router = APIRouter(prefix="/eligibility-rules", tags=["eligibility-rules"])


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
    # No income cross-check here: the numeric eligibility thresholds moved to
    # /eligibility-rules (M15 1d). This surface is shared infra only (sheet + pets + AI).
    return build_settings_response(db, user, save_app_settings(db, settings))


def _validate_rules(rules: EligibilityRules) -> None:
    if rules.income_max < rules.income_min:
        raise Problem(
            "invalid_settings",
            detail="Income maximum must be greater than or equal to income minimum.",
        )


@rules_router.get("", response_model=EligibilityRulesResponse)
def read_eligibility_rules(
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> EligibilityRulesResponse:
    """This member's effective eligibility rules and whether they are the shared committee
    default (no personal divergence yet) or the member's own."""
    rules, is_default = member_rules(db, user.id)
    return EligibilityRulesResponse(rules=rules, is_default=is_default)


@rules_router.put("", response_model=EligibilityRulesResponse)
def update_eligibility_rules(
    rules: EligibilityRules,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> EligibilityRulesResponse:
    """Upsert this member's own rules (copy-on-write divergence from the committee default).
    After saving, the member reads their own rules, so ``is_default`` is False."""
    _validate_rules(rules)
    saved = save_member_rules(db, user.id, rules)
    return EligibilityRulesResponse(rules=saved, is_default=False)
