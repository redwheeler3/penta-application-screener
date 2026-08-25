from fastapi import APIRouter, Depends
from pydantic.alias_generators import to_camel
from sqlalchemy.orm import Session

from app.ai.model_catalog import MODEL_CATALOG, model_spec, provider_is_configured
from app.ai.pass_catalog import AI_PASS_CATALOG
from app.api.dependencies import require_admin, require_current_user
from app.api.problems import Problem
from app.core.config import get_settings
from app.db.models import User
from app.db.session import get_db
from app.schemas.settings import (
    AIModelOption,
    AIPassOption,
    AppSettings,
    EligibilityCheckCatalog,
    EligibilityRules,
    EligibilityRulesResponse,
    SettingsResponse,
)
from app.services.eligibility_catalog import ELIGIBILITY_CHECK_CATALOG
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
    runtime = get_settings()
    return SettingsResponse(
        settings=settings,
        ai_model_options=[
            AIModelOption(
                model_id=model.model_id,
                label=model.label,
                provider=model.provider,
                supports_reasoning_effort=model.supports_reasoning_effort,
                configured=provider_is_configured(
                    model.provider,
                    openai_api_key=runtime.openai_api_key,
                    anthropic_api_key=runtime.anthropic_api_key,
                ),
            )
            for model in MODEL_CATALOG
        ],
        ai_passes=[
            AIPassOption(
                key=spec.key,
                label=spec.label,
                model_setting=to_camel(spec.model_attr),
                reasoning_setting=to_camel(spec.reasoning_attr),
            )
            for spec in AI_PASS_CATALOG
        ],
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
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> SettingsResponse:
    # Numeric eligibility thresholds live under /eligibility-rules. This endpoint
    # owns only the shared AI configuration.
    runtime = get_settings()
    unavailable = [
        model_id
        for model_id in settings.ai.selected_models()
        if not provider_is_configured(
            model_spec(model_id).provider,
            openai_api_key=runtime.openai_api_key,
            anthropic_api_key=runtime.anthropic_api_key,
        )
    ]
    if unavailable:
        raise Problem(
            "ai_provider_not_configured",
            detail="The selected model provider is not configured on this server.",
        )
    return build_settings_response(db, admin, save_app_settings(db, settings))


def _validate_rules(rules: EligibilityRules) -> None:
    if rules.income_max < rules.income_min:
        raise Problem(
            "invalid_settings",
            detail="Income maximum must be greater than or equal to income minimum.",
        )


@rules_router.get("/catalog", response_model=EligibilityCheckCatalog)
def read_eligibility_check_catalog(
    _user: User = Depends(require_current_user),
) -> EligibilityCheckCatalog:
    return ELIGIBILITY_CHECK_CATALOG


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
