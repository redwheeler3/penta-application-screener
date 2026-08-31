"""Read current and retained application answers into the editable form shape."""

from typing import Any

from pydantic import ValidationError

from app.db.models import Application
from app.schemas.applicant.answers import WorkingApplicationAnswers
from app.services.application_content import LEGACY_ESSAY_FIELDS


def submitted_answers_are_native(application: Application) -> bool:
    return _answers_are_native(application.raw_row or {})


def working_answers_for(application: Application) -> WorkingApplicationAnswers | None:
    """Return the best readable working copy without mutating the application."""
    stored = application.working_answers
    if stored is not None:
        parsed = _parse_current(stored)
        if parsed is not None:
            return parsed
        if not _answers_are_native(stored) and not submitted_answers_are_native(application):
            return _legacy_working_answers(application, stored)
        return None

    if submitted_answers_are_native(application):
        return _parse_current(application.raw_row or {})
    if application.raw_row:
        return _legacy_working_answers(application, application.raw_row)
    return None


def _parse_current(stored: dict[str, Any]) -> WorkingApplicationAnswers | None:
    try:
        return WorkingApplicationAnswers.model_validate(stored)
    except ValidationError:
        return None


def _answers_are_native(stored: dict[str, Any]) -> bool:
    return isinstance(stored.get("applicant"), dict)


def _legacy_working_answers(
    application: Application, row: dict[str, Any]
) -> WorkingApplicationAnswers:
    normalized = application.normalized or {}
    co_applicant_present = any(
        _text(row.get(key))
        for key in (
            "First name [2]",
            "Last name [2]",
            "Email address [2]",
            "Phone number (xxx-xxx-xxxx) [2]",
            "Relationship to applicant",
        )
    ) or bool(normalized.get("co_applicant_name"))

    children = []
    normalized_children = normalized.get("child_details") or []
    for index, suffix in enumerate(("[3]", "[4]", "[5]", "[6]")):
        normalized_child = (
            normalized_children[index]
            if index < len(normalized_children) and isinstance(normalized_children[index], dict)
            else {}
        )
        first_name = _text(row.get(f"First name {suffix}")) or _text(
            normalized_child.get("first_name")
        )
        last_name = _text(row.get(f"Last name {suffix}")) or _text(
            normalized_child.get("last_name")
        )
        if first_name or last_name or row.get(f"Age {suffix}") not in (None, ""):
            children.append(
                {"first_name": first_name, "last_name": last_name, "birth_date": ""}
            )
    declared_child_count = normalized.get("child_count")
    if isinstance(declared_child_count, int):
        while len(children) < min(declared_child_count, 20):
            children.append({"first_name": "", "last_name": "", "birth_date": ""})

    has_real_estate = normalized.get("has_real_estate")
    owns_current_home = False if has_real_estate is False else None
    owns_other_real_estate = False if has_real_estate is False else None

    return WorkingApplicationAnswers.model_validate(
        {
            "applicant": {
                "first_name": _text(row.get("First name")),
                "last_name": _text(row.get("Last name")),
                "birth_date": "",
                "phone": _text(row.get("Phone number (xxx-xxx-xxxx)")),
                "email": application.primary_email,
            },
            "co_applicant": (
                {
                    "first_name": _text(row.get("First name [2]")),
                    "last_name": _text(row.get("Last name [2]")),
                    "birth_date": "",
                    "phone": _text(row.get("Phone number (xxx-xxx-xxxx) [2]")),
                    "email": _text(row.get("Email address [2]")),
                    "relationship": _text(row.get("Relationship to applicant")),
                }
                if co_applicant_present
                else None
            ),
            "children": children,
            "current_address": {
                "street": _text(row.get("Street address")),
                "street_2": _text(row.get("Street address 2")) or None,
                "city": _text(row.get("City")),
                "province_or_state": _text(row.get("Province / State")),
                "postal_or_zip_code": _text(row.get("Postal / Zip Code")),
                "country": _text(row.get("Country")),
            },
            "lived_at_current_address_two_years": _yes_no(
                row.get("Have you lived at your current address for 2 years or more?")
            ),
            "owns_current_home": owns_current_home,
            "owns_other_real_estate": owns_other_real_estate,
            "current_landlord": _reference(row, "Current landlord"),
            "previous_landlord": _reference(row, "Previous landlord"),
            "essays": {
                "household_introduction": _legacy_essay(row, "About the household"),
                "skills_to_contribute": _legacy_essay(row, "Skills to contribute"),
                "previous_coop_experience": _legacy_essay(
                    row, "Previous co-op experience"
                ),
                "why_coop": _legacy_essay(row, "Why a co-op"),
                "additional_information": "",
            },
            "pets": (
                _text(normalized.get("pets_text"))
                or _text(row.get("If you have any pets, please describe them here."))
                or None
            ),
            "household_photo_link": _household_photo_link(row, normalized),
            "applicant_employment": _employment(row, ""),
            "co_applicant_employment": (
                _employment(row, " [2]") if co_applicant_present else None
            ),
            "applicant_income": normalized.get("applicant_income"),
            "co_applicant_income": (
                normalized.get("co_applicant_income") if co_applicant_present else None
            ),
        }
    )


def _employment(row: dict[str, Any], suffix: str) -> dict[str, Any]:
    manager_suffix = " [2]" if suffix else ""
    return {
        "status": None,
        "job_title": _text(row.get(f"Job title{suffix}")) or None,
        "company_name": _text(row.get(f"Company name{suffix}")) or None,
        "start_date": _text(row.get(f"Start date at this company{suffix}")) or None,
        "manager": _reference(row, "current manager", suffix=manager_suffix),
    }


def _reference(
    row: dict[str, Any], label: str, *, suffix: str = ""
) -> dict[str, str] | None:
    if label == "current manager":
        values = {
            "name": _text(row.get(f"Name of current manager{suffix}")),
            "email": _text(row.get(f"Email address of current manager{suffix}")),
            "phone": _text(
                row.get(f"Phone number (xxx-xxx-xxxx) of current manager{suffix}")
            ),
        }
    else:
        values = {
            "name": _text(row.get(f"{label} name")),
            "email": _text(row.get(f"{label} email address")),
            "phone": _text(row.get(f"{label} phone number (xxx-xxx-xxxx)")),
        }
    return values if any(values.values()) else None


def _legacy_essay(row: dict[str, Any], label: str) -> str:
    question = dict(LEGACY_ESSAY_FIELDS)[label]
    return _text(row.get(question))


def _household_photo_link(
    row: dict[str, Any], normalized: dict[str, Any]
) -> str | None:
    return (
        _text(normalized.get("household_photo_link"))
        or _text(row.get("household_photo_link"))
        or _text(
            row.get(
                "If you have a link to a photo of yourself and the members of your household, please include it here."
            )
        )
        or None
    )


def _yes_no(value: Any) -> bool | None:
    text = _text(value).lower()
    if text in {"yes", "y", "true", "1"}:
        return True
    if text in {"no", "n", "false", "0"}:
        return False
    return None


def _text(value: Any) -> str:
    return str(value or "").strip()
