from fastapi import APIRouter, Depends
from googleapiclient.errors import HttpError
from sqlalchemy.orm import Session

from app.api.dependencies import require_admin, require_current_user
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
from app.services.rules import (
    committee_default_rules,
    member_rules,
    reset_member_rules,
    save_committee_default_rules,
    save_member_rules,
)
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
    # /eligibility-rules (M15 1d; pets joined them in 1e). This surface is shared infra
    # only (sheet + AI).
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


@rules_router.delete("", response_model=EligibilityRulesResponse)
def reset_eligibility_rules(
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> EligibilityRulesResponse:
    """Reset this member to the committee default — drop their copy-on-write divergence (M15
    1f). Idempotent: a no-op if they never diverged. Returns the now-effective rules, which
    are the committee default (``is_default`` True)."""
    reset_member_rules(db, user.id)
    return EligibilityRulesResponse(rules=committee_default_rules(db), is_default=True)


@rules_router.get("/committee-default", response_model=EligibilityRules)
def read_committee_default_rules(
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> EligibilityRules:
    """The shared committee-default rules. Any member may read it — it's the baseline they
    follow until they diverge, and the Eligibility Settings page shows it as the "compared to
    committee default" reference (M15 1f lazy divergence diff)."""
    return committee_default_rules(db)


@rules_router.put("/committee-default", response_model=EligibilityRules)
def update_committee_default_rules(
    rules: EligibilityRules,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> EligibilityRules:
    """Admin-gated edit of the shared committee-default rules (M15 1f). Editing the default has
    ZERO side effects on member rows (Model A — no reconciliation, no write-fanout): a diverged
    member keeps their own rules until they reset; every non-diverged member reads the new
    default on their next read."""
    _validate_rules(rules)
    return save_committee_default_rules(db, rules)
