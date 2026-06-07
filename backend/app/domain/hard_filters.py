from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class FilterStatus(StrEnum):
    ELIGIBLE = "eligible"
    FILTERED_OUT = "filtered_out"
    NEEDS_REVIEW = "needs_review"


@dataclass(frozen=True)
class UnitRules:
    unit_size: str = "2br"
    min_income: int = 70_000
    max_income: int = 150_000


@dataclass(frozen=True)
class FilterReason:
    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FilterResult:
    status: FilterStatus
    reasons: list[FilterReason]


def evaluate_hard_filters(application: dict[str, Any], rules: UnitRules = UnitRules()) -> FilterResult:
    reasons: list[FilterReason] = []

    reasons.extend(_household_reasons(application, rules))
    reasons.extend(_income_reasons(application, rules))
    reasons.extend(_real_estate_reasons(application))
    reasons.extend(_pet_reasons(application))

    if any(reason.code.endswith("_unclear") for reason in reasons):
        return FilterResult(FilterStatus.NEEDS_REVIEW, reasons)

    if reasons:
        return FilterResult(FilterStatus.FILTERED_OUT, reasons)

    return FilterResult(FilterStatus.ELIGIBLE, [])


def _household_reasons(application: dict[str, Any], rules: UnitRules) -> list[FilterReason]:
    adult_count = application.get("adult_count")
    child_count = application.get("child_count")

    if not isinstance(adult_count, int) or not isinstance(child_count, int):
        return [
            FilterReason(
                code="household_unclear",
                message="Household composition could not be determined.",
                details={"adult_count": adult_count, "child_count": child_count},
            )
        ]

    if adult_count > 2:
        return [
            FilterReason(
                code="too_many_adults",
                message=f"Household has {adult_count} adults; maximum is 2.",
                details={"adult_count": adult_count},
            )
        ]

    if adult_count < 1:
        return [
            FilterReason(
                code="no_adults",
                message="Household must include at least 1 adult.",
                details={"adult_count": adult_count},
            )
        ]

    unit_size = rules.unit_size.lower()
    if unit_size == "1br":
        if child_count != 0:
            return [
                FilterReason(
                    code="household_size_ineligible",
                    message="1-bedroom units are for 1 or 2 adults.",
                    details={"child_count": child_count},
                )
            ]
        return []

    if unit_size == "2br":
        if child_count < 1 or child_count > 4:
            return [
                FilterReason(
                    code="household_size_ineligible",
                    message="2-bedroom units require 1 to 4 children under 18.",
                    details={"child_count": child_count},
                )
            ]
        return []

    if unit_size == "3br":
        if child_count < 2:
            return [
                FilterReason(
                    code="household_size_ineligible",
                    message="3-bedroom units require at least 2 children under 18.",
                    details={"child_count": child_count},
                )
            ]
        return []

    return [
        FilterReason(
            code="unit_size_unclear",
            message=f"Unit size rule is not configured for {rules.unit_size}.",
            details={"unit_size": rules.unit_size},
        )
    ]


def _income_reasons(application: dict[str, Any], rules: UnitRules) -> list[FilterReason]:
    income = application.get("household_income")
    if not isinstance(income, int | float):
        return [
            FilterReason(
                code="income_unclear",
                message="Household gross income could not be determined.",
                details={"household_income": income},
            )
        ]

    if income < rules.min_income:
        return [
            FilterReason(
                code="income_below_range",
                message=f"Household gross income is below ${rules.min_income:,}.",
                details={"household_income": income, "min_income": rules.min_income},
            )
        ]

    if income > rules.max_income:
        return [
            FilterReason(
                code="income_above_range",
                message=f"Household gross income is above ${rules.max_income:,}.",
                details={"household_income": income, "max_income": rules.max_income},
            )
        ]

    return []


def _real_estate_reasons(application: dict[str, Any]) -> list[FilterReason]:
    if application.get("has_real_estate") is True:
        return [
            FilterReason(
                code="owns_real_estate",
                message="Applicant owns real estate.",
                details={"has_real_estate": True},
            )
        ]
    return []


def _pet_reasons(application: dict[str, Any]) -> list[FilterReason]:
    dog_count = application.get("dog_count", 0)
    cat_count = application.get("cat_count", 0)
    other_pet_count = application.get("other_pet_count", 0)

    if not all(isinstance(count, int) for count in [dog_count, cat_count, other_pet_count]):
        return [
            FilterReason(
                code="pets_unclear",
                message="Pet information could not be determined.",
                details={
                    "dog_count": dog_count,
                    "cat_count": cat_count,
                    "other_pet_count": other_pet_count,
                },
            )
        ]

    if dog_count > 1 or cat_count > 1 or other_pet_count > 0:
        return [
            FilterReason(
                code="pet_rule_violation",
                message="Penta permits one dog and one cat per unit; other pets or additional pets require General Meeting approval.",
                details={
                    "dog_count": dog_count,
                    "cat_count": cat_count,
                    "other_pet_count": other_pet_count,
                },
            )
        ]

    return []

