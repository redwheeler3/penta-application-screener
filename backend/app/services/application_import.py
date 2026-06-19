import hashlib
import json
import re
from collections import OrderedDict
from datetime import date as date_type
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Application, ApplicationAIResult, ApplicationStatus, SyncRun
from app.domain.hard_filters import FilterReason, FilterStatus, RulesConfig, evaluate_hard_filters
from app.domain.status import apply_machine_status
from app.schemas.settings import AppSettings


EMAIL_ALIASES = ["email address", "applicant email", "email"]
APPLICANT_NAME_ALIASES = ["applicant name", "name", "applicant full name"]
CO_APPLICANT_NAME_ALIASES = ["co-applicant name", "co applicant name"]
ADULT_COUNT_ALIASES = ["adult_count", "adult count", "number of adults"]
CHILD_COUNT_ALIASES = [
    "child_count",
    "child count",
    "number of children",
    "number of children under 18 living in the unit on the move-in date",
    "how many children (under 18) will be living in the unit on the move in date?",
]
HOUSEHOLD_INCOME_ALIASES = [
    "household_income",
    "household income",
    "household gross yearly income",
    "total household income",
    "total yearly gross income for your household",
]
APPLICANT_INCOME_ALIASES = [
    "total yearly gross income for applicant",
    "applicant income",
    "applicant gross income",
]
CO_APPLICANT_INCOME_ALIASES = [
    "total yearly gross income for co-applicant",
    "co-applicant income",
    "co applicant income",
]
REAL_ESTATE_ALIASES = ["has_real_estate", "owns real estate", "do you own real estate"]
PETS_ALIASES = ["pets description", "pets", "pet description"]
APPLICANT_START_DATE_ALIASES = ["start date at this company"]
CO_APPLICANT_START_DATE_ALIASES = ["start date at this company [2]"]

# Free-text essay questions, keyed by their exact form column with a short
# committee-facing label. This is the single home for the essay field mapping;
# both import and the detail API read from here.
ESSAY_FIELDS: list[tuple[str, str]] = [
    (
        "About the household",
        "Please introduce yourself and your family, including your employment background, interests, and values.",
    ),
    (
        "Skills to contribute",
        "Please tell us about any skills you and the co-applicant could actively contribute to the running and maintenance of the co-op.",
    ),
    (
        "Previous co-op experience",
        "Please tell us about any previous co-op experience you or the co-applicant may have.",
    ),
    (
        "Why a co-op",
        "Describe why you want to live in a co-op and in what ways you would be a valuable member to the co-op.",
    ),
]


def extract_essays(row: dict[str, Any]) -> list[dict[str, str]]:
    """Pull the free-text essay answers out of a raw form row, in form order."""
    essays = []
    for label, column in ESSAY_FIELDS:
        answer = str(row.get(column, "") or "").strip()
        essays.append({"label": label, "question": column, "answer": answer})
    return essays


def import_applications_from_rows(
    db: Session,
    *,
    rows: list[dict[str, Any]],
    source_sheet_id: str,
    settings: AppSettings,
) -> SyncRun:
    latest_by_email: OrderedDict[str, dict[str, Any]] = OrderedDict()
    duplicate_count = 0

    for row in rows:
        email = normalize_email(_first_value(row, EMAIL_ALIASES))
        if not email:
            continue
        if email in latest_by_email:
            duplicate_count += 1
            del latest_by_email[email]
        latest_by_email[email] = row

    imported_count = 0
    updated_count = 0
    counts = {
        ApplicationStatus.ELIGIBLE: 0,
        ApplicationStatus.INELIGIBLE: 0,
    }

    rules = RulesConfig(
        unit_size=settings.unit_size,
        min_income=settings.income_min,
        max_income=settings.income_max,
        max_adults=settings.max_adults,
        min_adult_age=settings.min_adult_age,
        income_mismatch_tolerance=settings.income_mismatch_tolerance,
        disabled_rules=tuple(settings.disabled_rules),
    )

    for email, row in latest_by_email.items():
        raw_hash = hash_row(row)
        normalized = normalize_application(row)
        result = evaluate_hard_filters(normalized, rules)
        normalized = _make_json_safe(normalized)
        reason_payload = [reason_to_payload(reason) for reason in result.reasons]

        application = db.scalar(select(Application).where(Application.primary_email == email))
        if application is None:
            imported_count += 1
            application = Application(
                primary_email=email,
                applicant_name=normalized.get("applicant_name"),
                co_applicant_name=normalized.get("co_applicant_name"),
                raw_row=row,
                raw_row_hash=raw_hash,
                normalized=normalized,
                hard_filter_reasons=reason_payload,
            )
            db.add(application)
        else:
            updated_count += 1
            application.applicant_name = normalized.get("applicant_name")
            application.co_applicant_name = normalized.get("co_applicant_name")
            application.raw_row = row
            application.raw_row_hash = raw_hash
            application.normalized = normalized
            application.hard_filter_reasons = reason_payload

        # The rules actor preserves any prior AI flags' effect, and never
        # overrides a human-set status.
        apply_machine_status(
            application,
            has_reasons=bool(reason_payload),
            has_ai_flags=_has_ai_flags(db, application),
        )
        counts[application.status] += 1

    sync_run = SyncRun(
        source_sheet_id=source_sheet_id,
        row_count=len(rows),
        duplicate_count=duplicate_count,
        imported_count=imported_count,
        updated_count=updated_count,
        eligible_count=counts[ApplicationStatus.ELIGIBLE],
        filtered_out_count=counts[ApplicationStatus.INELIGIBLE],
    )
    db.add(sync_run)
    db.commit()
    db.refresh(sync_run)
    return sync_run


def normalize_application(row: dict[str, Any]) -> dict[str, Any]:
    pets_text = str(_first_value(row, PETS_ALIASES) or "")
    applicant_name = _form_full_name(row, "First name", "Last name") or _first_value(row, APPLICANT_NAME_ALIASES)
    co_applicant_name = _form_full_name(row, "First name [2]", "Last name [2]") or _first_value(
        row,
        CO_APPLICANT_NAME_ALIASES,
    )

    form_submission_email = str(row.get("Email Address", "") or "").strip()
    applicant_email = str(row.get("Email address", "") or "").strip()
    if not applicant_email:
        applicant_email = str(_first_value(row, EMAIL_ALIASES) or "").strip()

    return {
        "applicant_name": applicant_name,
        "co_applicant_name": co_applicant_name,
        "applicant_age": parse_int_signed(row.get("Age")),
        "co_applicant_age": parse_int_signed(row.get("Age [2]")),
        "adult_count": parse_int(_first_value(row, ADULT_COUNT_ALIASES))
        or infer_adult_count(applicant_name, co_applicant_name),
        "child_count": parse_child_count(_first_value(row, CHILD_COUNT_ALIASES)),
        "child_details": _extract_child_details(row),
        "household_income": parse_money(_first_value(row, HOUSEHOLD_INCOME_ALIASES)),
        "applicant_income": parse_money(_first_value(row, APPLICANT_INCOME_ALIASES)),
        "co_applicant_income": parse_money(_first_value(row, CO_APPLICANT_INCOME_ALIASES)),
        "has_real_estate": parse_bool(_first_value(row, REAL_ESTATE_ALIASES)),
        "pets_text": pets_text or None,
        "co_applicant_phone": str(row.get("Phone number (xxx-xxx-xxxx) [2]", "") or "").strip() or None,
        "co_applicant_email": str(row.get("Email address [2]", "") or "").strip() or None,
        "applicant_email": applicant_email or None,
        "form_submission_email": form_submission_email or None,
        "applicant_employment_start": parse_date(_first_value(row, APPLICANT_START_DATE_ALIASES)),
        "co_applicant_employment_start": parse_date(_first_value(row, CO_APPLICANT_START_DATE_ALIASES)),
    }


def _extract_child_details(row: dict[str, Any]) -> list[dict[str, Any]]:
    # After make_unique_headers:
    # Applicant: First name, Last name, Age
    # Co-applicant: First name [2], Last name [2], Age [2]
    # Child 1: First name [3], Last name [3], Age [3]
    # Child 2: First name [4], Last name [4], Age [4]
    # Child 3: First name [5], Last name [5], Age [5]
    # Child 4: First name [6], Last name [6], Age [6]
    children = []
    for suffix in ("[3]", "[4]", "[5]", "[6]"):
        first_name = str(row.get(f"First name {suffix}", "") or "").strip() or None
        last_name = str(row.get(f"Last name {suffix}", "") or "").strip() or None
        age = parse_int_signed(row.get(f"Age {suffix}"))

        if first_name or last_name or age is not None:
            children.append({"first_name": first_name, "last_name": last_name, "age": age})

    return children


def _form_full_name(row: dict[str, Any], first_name_key: str, last_name_key: str) -> str | None:
    first_name = str(row.get(first_name_key) or "").strip()
    last_name = str(row.get(last_name_key) or "").strip()
    full_name = " ".join(part for part in [first_name, last_name] if part)
    return full_name or None


def _first_value(row: dict[str, Any], aliases: list[str]) -> Any:
    lowered = {key.strip().lower(): value for key, value in row.items()}
    for alias in aliases:
        if alias in lowered:
            return lowered[alias]
    for key, value in lowered.items():
        if any(alias in key for alias in aliases):
            return value
    return None


def normalize_email(value: Any) -> str:
    return str(value or "").strip().lower()


def hash_row(row: dict[str, Any]) -> str:
    payload = json.dumps(row, sort_keys=True, ensure_ascii=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def parse_int(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    match = re.search(r"\d+", str(value or ""))
    if not match:
        return None
    return int(match.group())


def parse_int_signed(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    match = re.match(r"^-?\d+$", text)
    if match:
        return int(match.group())
    return None


def parse_date(value: Any) -> date_type | None:
    if isinstance(value, date_type):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    match = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", text)
    if match:
        try:
            return date_type(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            return None
    return None




def parse_child_count(value: Any) -> int | None:
    text = str(value or "").strip().lower()
    if "more than 4" in text:
        return 5
    return parse_int(text)


def parse_money(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    text = str(value or "").strip().lower()
    if not text:
        return None
    multiplier = 1000 if "k" in text else 1
    match = re.search(r"\d[\d,]*(?:\.\d+)?", text)
    if not match:
        return None
    return int(float(match.group().replace(",", "")) * multiplier)


def parse_bool(value: Any) -> bool | None:
    text = str(value or "").strip().lower()
    if text in {"yes", "y", "true", "1"}:
        return True
    if text in {"no", "n", "false", "0"}:
        return False
    return None


def infer_adult_count(applicant_name: str | None, co_applicant_name: str | None) -> int | None:
    if applicant_name and co_applicant_name:
        return 2
    if applicant_name:
        return 1
    return None




def _make_json_safe(data: dict[str, Any]) -> dict[str, Any]:
    result = {}
    for key, value in data.items():
        if isinstance(value, date_type):
            result[key] = value.isoformat()
        elif isinstance(value, list):
            result[key] = [_make_json_safe(item) if isinstance(item, dict) else item for item in value]
        elif isinstance(value, dict):
            result[key] = _make_json_safe(value)
        else:
            result[key] = value
    return result


def reason_to_payload(reason: FilterReason) -> dict[str, Any]:
    return {
        "code": reason.code,
        "message": reason.message,
        "details": reason.details,
    }


def _has_ai_flags(db: Session, application: Application) -> bool:
    """Whether the application's most recent quality-flag pass found any flags.

    A new application (no id yet) cannot have prior AI results.
    """
    if application.id is None:
        return False
    result = db.scalar(
        select(ApplicationAIResult)
        .where(
            ApplicationAIResult.application_id == application.id,
            ApplicationAIResult.kind == "quality_flags",
        )
        .order_by(ApplicationAIResult.created_at.desc())
    )
    return bool(result and (result.output or {}).get("flags"))
