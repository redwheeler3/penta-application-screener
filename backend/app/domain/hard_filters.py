from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Any


class FilterStatus(StrEnum):
    ELIGIBLE = "eligible"
    FILTERED_OUT = "filtered_out"


@dataclass(frozen=True)
class RulesConfig:
    unit_size: str = "2br"
    max_adults: int = 2
    min_income: int = 70_000
    max_income: int = 150_000
    income_mismatch_tolerance: int = 1_000
    min_adult_age: int = 19
    disabled_rules: tuple[str, ...] = ()
    today: date = field(default_factory=date.today)




@dataclass(frozen=True)
class FilterReason:
    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FilterResult:
    status: FilterStatus
    reasons: list[FilterReason]




def evaluate_hard_filters(
    application: dict[str, Any], rules: RulesConfig = RulesConfig()
) -> FilterResult:
    reasons: list[FilterReason] = []

    reasons.extend(_child_count_mismatch(application))
    reasons.extend(_child_age_over_18(application))
    reasons.extend(_applicant_under_19(application, rules))
    reasons.extend(_co_applicant_under_19(application, rules))
    reasons.extend(_child_age_exceeds_parent(application))
    reasons.extend(_income_below_range(application, rules))
    reasons.extend(_income_above_range(application, rules))
    reasons.extend(_income_arithmetic_mismatch(application, rules))
    reasons.extend(_real_estate_ownership(application))
    reasons.extend(_negative_number(application))
    reasons.extend(_future_employment_start(application, rules))
    reasons.extend(_co_applicant_incomplete(application))

    if rules.disabled_rules:
        reasons = [r for r in reasons if r.code not in rules.disabled_rules]

    if reasons:
        return FilterResult(FilterStatus.FILTERED_OUT, reasons)
    return FilterResult(FilterStatus.ELIGIBLE, [])








def _child_count_mismatch(application: dict[str, Any]) -> list[FilterReason]:
    child_count = application.get("child_count")
    child_details = application.get("child_details", [])

    if not isinstance(child_count, int) or child_count == 0:
        return []

    complete_blocks = sum(
        1
        for child in child_details
        if child.get("first_name") and child.get("last_name") and child.get("age") is not None
    )

    if complete_blocks != child_count:
        return [
            FilterReason(
                code="child_count_mismatch",
                message=f"Child count ({child_count}) doesn't match child details provided ({complete_blocks}).",
                details={"declared_count": child_count, "complete_blocks": complete_blocks},
            )
        ]
    return []


def _child_age_over_18(application: dict[str, Any]) -> list[FilterReason]:
    child_details = application.get("child_details", [])
    reasons = []

    for child in child_details:
        age = child.get("age")
        if isinstance(age, int) and age >= 18:
            reasons.append(
                FilterReason(
                    code="child_age_over_18",
                    message=f"Child '{child.get('first_name', '?')}' is {age}; must be under 18.",
                    details={"child_name": child.get("first_name"), "child_age": age},
                )
            )

    return reasons


def _applicant_under_19(
    application: dict[str, Any], rules: RulesConfig
) -> list[FilterReason]:
    age = application.get("applicant_age")
    if isinstance(age, int) and age < rules.min_adult_age:
        return [
            FilterReason(
                code="applicant_under_19",
                message=f"Applicant is {age}; must be at least {rules.min_adult_age}.",
                details={"applicant_age": age, "min_adult_age": rules.min_adult_age},
            )
        ]
    return []


def _co_applicant_under_19(
    application: dict[str, Any], rules: RulesConfig
) -> list[FilterReason]:
    age = application.get("co_applicant_age")
    if age is None:
        return []
    if isinstance(age, int) and age < rules.min_adult_age:
        return [
            FilterReason(
                code="co_applicant_under_19",
                message=f"Co-applicant is {age}; must be at least {rules.min_adult_age}.",
                details={"co_applicant_age": age, "min_adult_age": rules.min_adult_age},
            )
        ]
    return []


def _child_age_exceeds_parent(application: dict[str, Any]) -> list[FilterReason]:
    applicant_age = application.get("applicant_age")
    co_applicant_age = application.get("co_applicant_age")
    child_details = application.get("child_details", [])

    parent_ages = [a for a in [applicant_age, co_applicant_age] if isinstance(a, int)]
    if not parent_ages:
        return []

    min_parent_age = min(parent_ages)
    reasons = []

    for child in child_details:
        age = child.get("age")
        if isinstance(age, int) and age >= min_parent_age:
            reasons.append(
                FilterReason(
                    code="child_age_exceeds_parent",
                    message=f"Child '{child.get('first_name', '?')}' age ({age}) is >= youngest parent age ({min_parent_age}).",
                    details={"child_name": child.get("first_name"), "child_age": age, "min_parent_age": min_parent_age},
                )
            )

    return reasons




def _income_below_range(
    application: dict[str, Any], rules: RulesConfig
) -> list[FilterReason]:
    income = application.get("household_income")
    if not isinstance(income, int | float):
        return []
    if income < rules.min_income:
        return [
            FilterReason(
                code="income_below_range",
                message=f"Household gross income (${income:,.0f}) is below ${rules.min_income:,}.",
                details={"household_income": income, "min_income": rules.min_income},
            )
        ]
    return []


def _income_above_range(
    application: dict[str, Any], rules: RulesConfig
) -> list[FilterReason]:
    income = application.get("household_income")
    if not isinstance(income, int | float):
        return []
    if income > rules.max_income:
        return [
            FilterReason(
                code="income_above_range",
                message=f"Household gross income (${income:,.0f}) is above ${rules.max_income:,}.",
                details={"household_income": income, "max_income": rules.max_income},
            )
        ]
    return []


def _income_arithmetic_mismatch(
    application: dict[str, Any], rules: RulesConfig
) -> list[FilterReason]:
    applicant_income = application.get("applicant_income")
    co_applicant_income = application.get("co_applicant_income")
    household_income = application.get("household_income")

    if not isinstance(household_income, int | float):
        return []

    parts = []
    if isinstance(applicant_income, int | float):
        parts.append(applicant_income)
    if isinstance(co_applicant_income, int | float):
        parts.append(co_applicant_income)

    if not parts:
        return []

    expected = sum(parts)
    if abs(expected - household_income) > rules.income_mismatch_tolerance:
        return [
            FilterReason(
                code="income_arithmetic_mismatch",
                message=f"Stated household income (${household_income:,.0f}) doesn't match sum of individual incomes (${expected:,.0f}).",
                details={
                    "applicant_income": applicant_income,
                    "co_applicant_income": co_applicant_income,
                    "household_income": household_income,
                    "expected_total": expected,
                },
            )
        ]
    return []


def _real_estate_ownership(application: dict[str, Any]) -> list[FilterReason]:
    if application.get("has_real_estate") is True:
        return [
            FilterReason(
                code="owns_real_estate",
                message="Applicant owns real estate.",
                details={"has_real_estate": True},
            )
        ]
    return []




def _negative_number(application: dict[str, Any]) -> list[FilterReason]:
    checks = [
        ("applicant_age", application.get("applicant_age")),
        ("co_applicant_age", application.get("co_applicant_age")),
        ("household_income", application.get("household_income")),
        ("applicant_income", application.get("applicant_income")),
        ("co_applicant_income", application.get("co_applicant_income")),
    ]

    for child in application.get("child_details", []):
        age = child.get("age")
        if age is not None:
            checks.append((f"child_age_{child.get('first_name', '?')}", age))

    reasons = []
    for field_name, value in checks:
        if isinstance(value, int | float) and value < 0:
            reasons.append(
                FilterReason(
                    code="negative_number",
                    message=f"Field '{field_name}' has negative value ({value}).",
                    details={"field": field_name, "value": value},
                )
            )

    return reasons




def _future_employment_start(
    application: dict[str, Any], rules: RulesConfig
) -> list[FilterReason]:
    reasons = []
    for field_key in ("applicant_employment_start", "co_applicant_employment_start"):
        start_date = application.get(field_key)
        if isinstance(start_date, date) and start_date > rules.today:
            reasons.append(
                FilterReason(
                    code="future_employment_start",
                    message=f"Employment start date ({start_date}) is in the future.",
                    details={"field": field_key, "start_date": str(start_date), "today": str(rules.today)},
                )
            )
    return reasons


def _co_applicant_incomplete(application: dict[str, Any]) -> list[FilterReason]:
    co_app_fields = [
        application.get("co_applicant_name"),
        application.get("co_applicant_age"),
        application.get("co_applicant_phone"),
        application.get("co_applicant_email"),
    ]

    filled = [f for f in co_app_fields if f]
    if 0 < len(filled) < len(co_app_fields):
        return [
            FilterReason(
                code="co_applicant_incomplete",
                message=f"Co-applicant details are partially filled ({len(filled)}/{len(co_app_fields)} fields).",
                details={"filled_count": len(filled), "total_fields": len(co_app_fields)},
            )
        ]
    return []


