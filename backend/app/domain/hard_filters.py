from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Any

# Single source of truth for hard-filter threshold defaults. RulesConfig and the
# AppSettings schema both reference these (settings imports the domain, never the
# reverse), so a default can't drift between the two layers.
DEFAULT_MIN_INCOME = 70_000
DEFAULT_MAX_INCOME = 150_000
DEFAULT_MIN_ADULT_AGE = 18
DEFAULT_MAX_CHILD_AGE = 17
DEFAULT_MIN_CHILDREN = 1
DEFAULT_MAX_CHILDREN = 4
DEFAULT_MAX_DOGS = 1
DEFAULT_MAX_CATS = 1
DEFAULT_ALLOW_OTHER_PETS = False


class EmploymentRequirement(StrEnum):
    NONE = "none"
    AT_LEAST_ONE = "at_least_one"
    ALL = "all"

# The reason code for a pet-limit violation. Named because it is load-bearing beyond this
# module: status resolution treats it specially (M15 1g) — a pet verdict needs the AI to
# extract pet counts from free text first, so it can only land at Screen, and it attributes
# to the AI status source, not Rules. Every other hard-filter reason is Sync-knowable (Rules).
PETS_OVER_LIMIT_CODE = "pets_over_limit"


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
    max_dogs: int = DEFAULT_MAX_DOGS
    max_cats: int = DEFAULT_MAX_CATS
    allow_other_pets: bool = DEFAULT_ALLOW_OTHER_PETS
    employment_requirement: EmploymentRequirement = EmploymentRequirement.NONE
    # Checks the member has switched off (M15 1g Move 3, renamed from disabled_rules). ONE
    # flat set spanning both kinds of eligibility check: deterministic hard-filter reason
    # codes (income_below_range, …) AND AI screening flag categories (fake_contact, …). The
    # two namespaces are disjoint, so this filter drops the matching REASON codes and harmlessly
    # ignores any flag-category strings — the flag half is applied separately (see
    # ``services/eligibility.active_flags``). A disabled check is hidden AND non-gating for
    # that member, matching how a disabled reason already behaves.
    disabled_checks: tuple[str, ...] = ()
    today: date = field(default_factory=date.today)


@dataclass(frozen=True)
class PetFacts:
    """The extracted pet inventory the pet hard filter reads — the domain mirror of the
    AI ``PetFacts`` schema (M15 1e). Kept in the domain layer (no pydantic) so
    ``evaluate_hard_filters`` stays a pure function with no schema/AI import."""

    dogs: int = 0
    cats: int = 0
    other_pets: tuple[str, ...] = ()


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
    application: dict[str, Any],
    rules: RulesConfig = RulesConfig(),
    *,
    pet_facts: PetFacts | None = None,
) -> FilterResult:
    """Evaluate every hard filter over one normalized application, returning the reasons
    it fails (empty = eligible).

    ``pet_facts`` is the one input that does NOT come from ``application`` (normalized): pet
    counts are extracted by the screening AI pass, not derived from the raw row, so they ride
    in separately and are OPTIONAL (M15 1e). When ``None`` the pet check is skipped entirely
    — deliberately, so the pre-screen callers (import; the screening-eligibility gate) don't
    gate on facts that only exist AFTER screening. The on-read eligibility path loads the
    screening result and passes ``pet_facts`` in, so pets gate per member there.
    """
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
    reasons.extend(_employment_requirement(application, rules))
    reasons.extend(_future_employment_start(application, rules))
    reasons.extend(_co_applicant_incomplete(application))
    if pet_facts is not None:
        reasons.extend(_pets_over_limit(pet_facts, rules))

    if rules.disabled_checks:
        reasons = [r for r in reasons if r.code not in rules.disabled_checks]

    status = FilterStatus.FILTERED_OUT if reasons else FilterStatus.ELIGIBLE
    return FilterResult(status, reasons)


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


def _pets_over_limit(pet_facts: PetFacts, rules: RulesConfig) -> list[FilterReason]:
    """The per-member pet policy, applied deterministically to extracted pet counts (M15
    1e). One reason per violated category (too many dogs, too many cats, a disallowed other
    pet) — all under the single ``pets_over_limit`` code so the detail view maps them to the
    pets field uniformly. Pets are judged HERE, not by the screening AI, because the limits
    are per-member: the same household is within one member's policy and over another's."""
    reasons: list[FilterReason] = []
    if pet_facts.dogs > rules.max_dogs:
        reasons.append(
            FilterReason(
                code=PETS_OVER_LIMIT_CODE,
                message=f"Household has {pet_facts.dogs} dog(s); at most {rules.max_dogs} allowed.",
                details={"kind": "dogs", "count": pet_facts.dogs, "max": rules.max_dogs},
            )
        )
    if pet_facts.cats > rules.max_cats:
        reasons.append(
            FilterReason(
                code=PETS_OVER_LIMIT_CODE,
                message=f"Household has {pet_facts.cats} cat(s); at most {rules.max_cats} allowed.",
                details={"kind": "cats", "count": pet_facts.cats, "max": rules.max_cats},
            )
        )
    if pet_facts.other_pets and not rules.allow_other_pets:
        listed = ", ".join(pet_facts.other_pets)
        reasons.append(
            FilterReason(
                code=PETS_OVER_LIMIT_CODE,
                message=f"Household has pets other than dogs and cats ({listed}); only dogs and cats are allowed.",
                details={"kind": "other", "other_pets": list(pet_facts.other_pets)},
            )
        )
    return reasons


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
        if isinstance(start_date, str):
            try:
                start_date = date.fromisoformat(start_date)
            except ValueError:
                start_date = None
        if isinstance(start_date, date) and start_date > rules.today:
            reasons.append(
                FilterReason(
                    code="future_employment_start",
                    message=f"Employment start date ({start_date}) is in the future.",
                    details={"field": field_key, "start_date": str(start_date), "today": str(rules.today)},
                )
            )
    return reasons


def _employment_requirement(
    application: dict[str, Any], rules: RulesConfig
) -> list[FilterReason]:
    if rules.employment_requirement == EmploymentRequirement.NONE:
        return []

    applicant_status = application.get("applicant_employment_status")
    co_applicant_status = application.get("co_applicant_employment_status")
    valid_statuses = {"employed", "self_employed", "unemployed"}
    if applicant_status not in valid_statuses:
        return []
    if co_applicant_status is not None and co_applicant_status not in valid_statuses:
        return []
    explicit_statuses = [applicant_status]
    if co_applicant_status is not None:
        explicit_statuses.append(co_applicant_status)

    working_statuses = {"employed", "self_employed"}
    requirement_met = (
        any(status in working_statuses for status in explicit_statuses)
        if rules.employment_requirement == EmploymentRequirement.AT_LEAST_ONE
        else all(status in working_statuses for status in explicit_statuses)
    )
    if requirement_met:
        return []
    return [
        FilterReason(
            code="employment_requirement_not_met",
            message="The household does not meet the employment requirement.",
            details={"requirement": rules.employment_requirement.value},
        )
    ]


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


