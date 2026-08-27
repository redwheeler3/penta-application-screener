"""Read the committed synthetic CSV into canonical application answers."""

import csv
import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.schemas.applicant.answers import CanonicalApplicationAnswers


@dataclass(frozen=True)
class SyntheticFixtureRecord:
    submitted_at: datetime
    answers: CanonicalApplicationAnswers


def read_synthetic_fixture(path: Path) -> Iterator[SyntheticFixtureRecord]:
    with path.open(encoding="utf-8", newline="") as source:
        for row in csv.DictReader(source):
            submitted_at = datetime.fromisoformat(row["submitted_at"])
            if submitted_at.tzinfo is None:
                submitted_at = submitted_at.replace(tzinfo=UTC)
            yield SyntheticFixtureRecord(
                submitted_at=submitted_at,
                answers=CanonicalApplicationAnswers.model_validate(_answers(row)),
            )


def _nested(row: dict[str, str], prefix: str) -> dict[str, str]:
    marker = f"{prefix}."
    return {
        key.removeprefix(marker): value
        for key, value in row.items()
        if key.startswith(marker) and value
    }


def _reference(row: dict[str, str], prefix: str) -> dict[str, str] | None:
    return _nested(row, prefix) or None


def _boolean(row: dict[str, str], key: str) -> bool:
    value = row[key].strip().lower()
    if value not in {"true", "false"}:
        raise ValueError(f"{key} must be 'true' or 'false'")
    return value == "true"


def _employment(row: dict[str, str], prefix: str) -> dict | None:
    employment = _nested(row, prefix)
    if not employment:
        return None
    manager = _reference(row, f"{prefix}.manager")
    employment = {
        key: value for key, value in employment.items() if not key.startswith("manager.")
    }
    employment["manager"] = manager
    return employment


def _answers(row: dict[str, str]) -> dict:
    co_applicant = _nested(row, "co_applicant")
    return {
        "applicant": _nested(row, "applicant"),
        "co_applicant": co_applicant or None,
        "children": json.loads(row["children_json"]),
        "current_address": _nested(row, "current_address"),
        "lived_at_current_address_two_years": _boolean(
            row, "lived_at_current_address_two_years"
        ),
        "owns_current_home": _boolean(row, "owns_current_home"),
        "owns_other_real_estate": _boolean(row, "owns_other_real_estate"),
        "current_landlord": _reference(row, "current_landlord"),
        "previous_landlord": _reference(row, "previous_landlord"),
        "essays": _nested(row, "essays"),
        "pets": row["pets"] or None,
        "household_photo_link": row["household_photo_link"] or None,
        "applicant_employment": _employment(row, "applicant_employment"),
        "co_applicant_employment": _employment(row, "co_applicant_employment"),
        "applicant_income": row["applicant_income"],
        "co_applicant_income": row["co_applicant_income"] or None,
    }
