"""Shared structured-fact view of an applicant for the discovery and scoring AI
passes.

Both passes feed the model the *same* subset of normalized fields alongside the
essays — defined once here so a dimension discovered from a fact is scoreable from
the identical fact. Included: household composition, income (total + split),
employment tenure, pets. Structured names, contact identifiers and birth dates are
excluded. Adult and child ages come from the frozen submitted projection.
Real-estate ownership is excluded (a hard filter, so constant across eligible
applicants). Several included fields are also hard-filter rules everyone passed, so
the passes read them for *residual* variation, not the pass/fail fact.
"""

from __future__ import annotations

from app.db.models import Application

# Normalized keys sent to the model, ordered for readable prompt JSON.
_FACT_KEYS = (
    "adult_count",
    "child_count",
    "applicant_age",
    "co_applicant_age",
    "child_details",
    "household_income",
    "applicant_income",
    "co_applicant_income",
    "applicant_employment_start",
    "co_applicant_employment_start",
    "pets_text",
)

def applicant_facts(application: Application) -> dict[str, object]:
    """The screening-relevant structured fields for one applicant. Only keys present
    in the normalized blob are returned, so a missing field is absent, not null.
    """
    return facts_from_normalized(application.normalized or {})


def facts_from_normalized(normalized: dict) -> dict[str, object]:
    facts = {key: normalized[key] for key in _FACT_KEYS if key in normalized}
    if "child_details" in facts:
        facts["child_details"] = _child_fields(facts["child_details"], ("age",))
    return facts


def screening_fields(normalized: dict) -> dict[str, object]:
    """Names support integrity checks; ages are supplied without birth dates."""
    fields = {key: normalized.get(key) for key in (
        "applicant_name", "co_applicant_name", "applicant_age", "co_applicant_age", "child_details", "pets_text",
        "applicant_email", "co_applicant_email", "co_applicant_phone",
    )}
    fields["child_details"] = _child_fields(fields["child_details"], ("first_name", "last_name", "age"))
    return fields


def _child_fields(children: list[dict] | None, keys: tuple[str, ...]) -> list[dict] | None:
    if children is None:
        return None
    return [{key: child[key] for key in keys if key in child} for child in children]
