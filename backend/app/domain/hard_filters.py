from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Any

# The single source of truth for hard-filter threshold defaults. Both the
# RulesConfig dataclass (below) and the AppSettings schema reference these, so a
# default can't drift between the domain layer and the settings layer. They live
# here, in the pure domain module, because they are screening-domain facts; the
# settings schema imports them, never the reverse (keeps the domain dependency-free).
DEFAULT_MIN_INCOME = 70_000
DEFAULT_MAX_INCOME = 150_000
DEFAULT_MIN_ADULT_AGE = 18
DEFAULT_MAX_CHILD_AGE = 17
DEFAULT_MIN_CHILDREN = 1
DEFAULT_MAX_CHILDREN = 4


class FilterStatus(StrEnum):
    ELIGIBLE = "eligible"
    FILTERED_OUT = "filtered_out"


@dataclass(frozen=True)
class RulesConfig:
    min_income: int = DEFAULT_MIN_INCOME
    max_income: int = DEFAULT_MAX_INCOME
    min_adult_age: int = DEFAULT_MIN_ADULT_AGE
    max_child_age: int = DEFAULT_MAX_CHILD_AGE
    min_children: int = DEFAULT_MIN_CHILDREN
    max_children: int = DEFAULT_MAX_CHILDREN
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
    reasons.extend(_too_few_children(application, rules))
    reasons.extend(_too_many_children(application, rules))
    reasons.extend(_child_age_over_max(application, rules))
    reasons.extend(_applicant_under_min_age(application, rules))
    reasons.extend(_co_applicant_under_min_age(application, rules))
    reasons.extend(_child_age_exceeds_parent(application))
    reasons.extend(_income_below_range(application, rules))
    reasons.extend(_income_above_range(application, rules))
    reasons.extend(_income_arithmetic_mismatch(application))
    reasons.extend(_owns_real_estate(application))
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


def _child_age_over_max(
    application: dict[str, Any], rules: RulesConfig
) -> list[FilterReason]:
    child_details = application.get("child_details", [])
    reasons = []

    for child in child_details:
        age = child.get("age")
        if isinstance(age, int) and age > rules.max_child_age:
            reasons.append(
                FilterReason(
                    code="child_age_over_max",
                    message=f"Child '{child.get('first_name', '?')}' is {age}; must be at most {rules.max_child_age}.",
                    details={"child_name": child.get("first_name"), "child_age": age, "max_child_age": rules.max_child_age},
                )
            )

    return reasons


def _too_few_children(
    application: dict[str, Any], rules: RulesConfig
) -> list[FilterReason]:
    child_count = application.get("child_count")
    if not isinstance(child_count, int):
        return []
    if child_count < rules.min_children:
        return [
            FilterReason(
                code="too_few_children",
                message=f"Household has {child_count} child(ren); at least {rules.min_children} required.",
                details={"child_count": child_count, "min_children": rules.min_children},
            )
        ]
    return []


def _too_many_children(
    application: dict[str, Any], rules: RulesConfig
) -> list[FilterReason]:
    child_count = application.get("child_count")
    if not isinstance(child_count, int):
        return []
    if child_count > rules.max_children:
        return [
            FilterReason(
                code="too_many_children",
                message=f"Household has {child_count} child(ren); at most {rules.max_children} allowed.",
                details={"child_count": child_count, "max_children": rules.max_children},
            )
        ]
    return []


def _applicant_under_min_age(
    application: dict[str, Any], rules: RulesConfig
) -> list[FilterReason]:
    age = application.get("applicant_age")
    if isinstance(age, int) and age < rules.min_adult_age:
        return [
            FilterReason(
                code="applicant_under_min_age",
                message=f"Applicant is {age}; must be at least {rules.min_adult_age}.",
                details={"applicant_age": age, "min_adult_age": rules.min_adult_age},
            )
        ]
    return []


def _co_applicant_under_min_age(
    application: dict[str, Any], rules: RulesConfig
) -> list[FilterReason]:
    age = application.get("co_applicant_age")
    if age is None:
        return []
    if isinstance(age, int) and age < rules.min_adult_age:
        return [
            FilterReason(
                code="co_applicant_under_min_age",
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


def _income_arithmetic_mismatch(application: dict[str, Any]) -> list[FilterReason]:
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
    if expected != household_income:
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


def _owns_real_estate(application: dict[str, Any]) -> list[FilterReason]:
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


