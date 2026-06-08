import hashlib
import json
import re
from collections import OrderedDict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Application, HardFilterStatus, SyncRun
from app.domain.hard_filters import FilterReason, FilterStatus, UnitRules, evaluate_hard_filters
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
INCOME_ALIASES = [
    "household_income",
    "household income",
    "household gross yearly income",
    "total household income",
    "total yearly gross income for your household",
]
REAL_ESTATE_ALIASES = ["has_real_estate", "owns real estate", "do you own real estate"]
PETS_ALIASES = ["pets description", "pets", "pet description"]


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
        HardFilterStatus.ELIGIBLE: 0,
        HardFilterStatus.FILTERED_OUT: 0,
        HardFilterStatus.NEEDS_REVIEW: 0,
    }

    rules = UnitRules(unit_size=settings.unit_size, min_income=settings.income_min, max_income=settings.income_max)

    for email, row in latest_by_email.items():
        raw_hash = hash_row(row)
        normalized = normalize_application(row)
        result = evaluate_hard_filters(normalized, rules)
        status = HardFilterStatus(result.status.value)
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
                hard_filter_status=status,
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
            application.hard_filter_status = status
            application.hard_filter_reasons = reason_payload

        counts[status] += 1

    sync_run = SyncRun(
        source_sheet_id=source_sheet_id,
        row_count=len(rows),
        duplicate_count=duplicate_count,
        imported_count=imported_count,
        updated_count=updated_count,
        eligible_count=counts[HardFilterStatus.ELIGIBLE],
        filtered_out_count=counts[HardFilterStatus.FILTERED_OUT],
        needs_review_count=counts[HardFilterStatus.NEEDS_REVIEW],
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
    return {
        "applicant_name": applicant_name,
        "co_applicant_name": co_applicant_name,
        "adult_count": parse_int(_first_value(row, ADULT_COUNT_ALIASES))
        or infer_adult_count(applicant_name, co_applicant_name),
        "child_count": parse_child_count(_first_value(row, CHILD_COUNT_ALIASES)),
        "household_income": parse_money(_first_value(row, INCOME_ALIASES)),
        "has_real_estate": parse_bool(_first_value(row, REAL_ESTATE_ALIASES)),
        "dog_count": count_pet_mentions(pets_text, "dog"),
        "cat_count": count_pet_mentions(pets_text, "cat"),
        "other_pet_count": infer_other_pet_count(pets_text),
    }


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


def count_pet_mentions(text: str, pet_type: str) -> int:
    if not text.strip():
        return 0
    matches = re.findall(rf"\b{pet_type}s?\b", text.lower())
    return len(matches)


def infer_other_pet_count(text: str) -> int:
    lowered = text.lower()
    if not lowered.strip():
        return 0
    known_words = {
        "a",
        "and",
        "cat",
        "cats",
        "dog",
        "dogs",
        "n",
        "na",
        "no",
        "none",
        "one",
        "pet",
        "pets",
    }
    words = set(re.findall(r"[a-z]+", lowered))
    return 0 if words <= known_words else 1


def reason_to_payload(reason: FilterReason) -> dict[str, Any]:
    return {
        "code": reason.code,
        "message": reason.message,
        "details": reason.details,
    }
