"""Shared structured-fact view of an applicant for the discovery and scoring AI
passes.

Both passes feed the model the *same* subset of normalized fields alongside the
essays — defined once here so a dimension discovered from a fact is scoreable from
the identical fact. Included: household composition, income (total + split),
employment tenure, pets. Adult contact identifiers are excluded; canonical child
details include names and birth dates alongside their submission-time ages.
Real-estate ownership is excluded (a hard filter, so constant across eligible
applicants). Several included fields are also hard-filter rules everyone passed, so
the passes read them for *residual* variation, not the pass/fail fact.
"""

from __future__ import annotations

from app.db.models import Application

# Normalized keys sent to the model. Ordered for readable prompt JSON. Ages are
# included (the operator opted in); child details also include identifying fields.
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
    return {key: normalized[key] for key in _FACT_KEYS if key in normalized}


def screening_fields(normalized: dict) -> dict[str, object]:
    """The ordered structured fields consumed by the integrity prompt."""
    return {key: normalized.get(key) for key in (
        "applicant_name", "co_applicant_name", "child_details", "pets_text",
        "applicant_email", "co_applicant_email", "co_applicant_phone",
    )}
