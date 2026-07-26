from fastapi import APIRouter, Depends
from google.auth.exceptions import RefreshError
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
    SheetCodeExchangeRequest,
    SheetLinkRequest,
    google_sheet_url_from_id,
)
from app.services.google_credentials import (
    exchange_auth_code,
    get_google_token,
    save_google_token,
)
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
        # Read the title with the DESIGNATED reader's token (it's the one that can access the
        # linked file post-M18), falling back to the viewing user's own token. The title is a
        # nice-to-have label, so ANY failure just drops it — a revoked/expired token raises
        # RefreshError (during refresh, before any HTTP call), which must be caught alongside
        # HttpError or loading Settings 500s (seen right after an M18 deploy, pre-relink).
        reader_id = settings.google_sheet_reader_user_id or user.id
        token = get_google_token(db, user_id=reader_id)
        if token is not None:
            try:
                sheet_title = fetch_sheet_title(
                    sheet_id=settings.google_sheet_id,
                    token=token,
                    settings=get_settings(),
                )
            except (HttpError, RefreshError):
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
    # only (sheet + AI). NB: google_sheet_id / google_sheet_reader_user_id are set via
    # /settings/link-sheet (the Picker flow), not by hand-editing this blob.
    return build_settings_response(db, user, save_app_settings(db, settings))


@router.post("/exchange-sheet-code")
def exchange_sheet_code(
    body: SheetCodeExchangeRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Exchange the GIS code-model auth code for tokens (M18). Stores the resulting token
    (with refresh, for durable sync) as the admin's credential, and returns the access token
    for the browser to open the Picker with. Because this token comes from the INTERACTIVE
    auth-code grant, a file picked with it is properly drive.file-authorized — which a
    server-refreshed token is not. Admin-only."""
    try:
        token = exchange_auth_code(code=body.code, settings=get_settings())
    except Exception as exc:
        raise Problem(
            "sheet_auth_failed",
            detail="Couldn't complete Google authorization. Try Connect response sheet again.",
        ) from exc

    access_token = token.get("access_token")
    if not access_token:
        raise Problem(
            "sheet_auth_failed",
            detail="Google authorization returned no access token. Try again.",
        )
    # Re-consent may omit refresh_token; preserve the admin's existing one so durable sync
    # keeps working. Then store as this admin's credential (they become the designated reader
    # when they finish linking a sheet).
    existing = get_google_token(db, user_id=admin.id) or {}
    if not token.get("refresh_token") and existing.get("refresh_token"):
        token["refresh_token"] = existing["refresh_token"]
    save_google_token(db, user_id=admin.id, token=token)
    return {"accessToken": access_token}


@router.post("/link-sheet", response_model=SettingsResponse)
def link_sheet(
    body: SheetLinkRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> SettingsResponse:
    """Link the response sheet the admin picked in the Google Picker (M18). By now the admin
    has run exchange-sheet-code, so their stored token came from the interactive drive.file
    grant and can read the file they picked. We verify by reading the sheet's title with THEIR
    token before saving; on success we record the sheet id and mark this admin the designated
    reader, so all future syncs read with their (offline, refreshing) token — members never
    need a Drive/Sheets scope."""
    token = get_google_token(db, user_id=admin.id)
    if token is None:
        raise Problem(
            "sheet_reader_unavailable",
            detail="Your Google connection is missing. Click Connect response sheet to grant access.",
        )

    # Verify the picked file is actually reachable with this admin's drive.file token before
    # committing it as the source — a wrong/unshared file or a token lacking drive.file fails
    # here rather than silently breaking every future sync.
    try:
        title = fetch_sheet_title(sheet_id=body.file_id, token=token, settings=get_settings())
    except HttpError as exc:
        raise Problem(
            "sheet_read_failed",
            detail=(
                "Couldn't read that sheet with your Google access. Re-connect via "
                "Connect response sheet and pick the file again."
            ),
        ) from exc
    if title is None:
        raise Problem(
            "sheet_read_failed",
            detail="Couldn't read that sheet. Re-connect and pick the response sheet again.",
        )

    settings = get_app_settings(db)
    settings.google_sheet_id = body.file_id
    settings.google_sheet_reader_user_id = admin.id
    return build_settings_response(db, admin, save_app_settings(db, settings))


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
