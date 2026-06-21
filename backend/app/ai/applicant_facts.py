"""Shared structured-fact view of an applicant for the milestone-7 AI passes.

Both pattern discovery and dimension scoring feed the model the *same* subset of
the normalized structured fields, alongside the essays. Defining it once here
keeps the two passes from drifting — a dimension discovered from a fact must be
scoreable from the identical fact.

What is included: household composition, income (total + split), employment
tenure, pets. What is deliberately excluded: names, emails, phone numbers
(identifiers with no screening value), and real-estate ownership — it is a hard
filter, so every eligible applicant is uniformly a non-owner (barring a rare
human override) and it carries no residual signal to discover or score.

Eligibility-overlap note: several of these fields are also hard-filter rules
(income band, real-estate ownership, pet policy, household-vs-unit size), which
every eligible applicant already passed. The passes therefore instruct the model
to read these for *residual* variation (income mix, position within band,
employment tenure, etc.), not the pass/fail fact, which is constant across the
eligible pool. See FILTERED_FACTS_NOTE.
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
    """The screening-relevant structured fields for one applicant.

    Only keys present in the normalized blob are returned, so a missing field is
    simply absent rather than a null the model might over-read.
    """
    normalized = application.normalized or {}
    return {key: normalized[key] for key in _FACT_KEYS if key in normalized}
