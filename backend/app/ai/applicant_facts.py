"""Shared structured-fact view of an applicant for the discovery and scoring AI
passes.

Both passes feed the model the *same* subset of normalized fields alongside the
essays — defined once here so a dimension discovered from a fact is scoreable from
the identical fact. Included: household composition, income (total + split),
employment tenure, pets. Excluded: identifiers (names/emails/phones, no screening
value) and real-estate ownership (a hard filter, so constant across eligible
applicants). Several included fields are also hard-filter rules everyone passed, so
the passes read them for *residual* variation, not the pass/fail fact — see
FILTERED_FACTS_NOTE.
"""

from __future__ import annotations

from app.db.models import Application

# Normalized keys sent to the model. Ordered for readable prompt JSON. Ages are
# included (the operator opted in); names/emails/phones are not.
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

# Shared prompt fragment both passes use so the model treats already-filtered
# fields as residual signal, not pass/fail facts.
FILTERED_FACTS_NOTE = (
    "Every applicant here already passed the deterministic hard filters "
    "(income within the co-op's band, pets within policy, household size within "
    "the unit). So do NOT treat the pass/fail fact as a differentiator — it is "
    "constant across this pool. Read the structured fields only for the "
    "variation that REMAINS meaningful among applicants who all already qualify: "
    "e.g. income mix between applicants, position within the allowed band, "
    "employment tenure/stability, household make-up relative to the unit. Never "
    "use age, family structure, or any protected characteristic as a basis for a "
    "dimension or a score."
)


def applicant_facts(application: Application) -> dict[str, object]:
    """The screening-relevant structured fields for one applicant. Only keys present
    in the normalized blob are returned, so a missing field is absent, not null.
    """
    normalized = application.normalized or {}
    return {key: normalized[key] for key in _FACT_KEYS if key in normalized}
