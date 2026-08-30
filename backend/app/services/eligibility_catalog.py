"""Member-facing descriptions of the eligibility checks implemented by the backend."""

from app.schemas.settings import EligibilityCheck, EligibilityCheckCatalog

ELIGIBILITY_CHECK_CATALOG = EligibilityCheckCatalog(
    deterministic=[
        EligibilityCheck(id="applicant_under_min_age", label="Applicant under minimum age", description="The primary applicant is younger than the minimum adult age."),
        EligibilityCheck(id="child_age_exceeds_parent", label="Child age exceeds parent", description="A listed child's age is at or above the youngest parent's age."),
        EligibilityCheck(id="child_age_over_max", label="Child over max age", description="A listed child is older than the maximum child age."),
        EligibilityCheck(id="child_count_mismatch", label="Child count mismatch", description="The stated number of children doesn't match the child details provided."),
        EligibilityCheck(id="co_applicant_incomplete", label="Co-applicant incomplete", description="Co-applicant details are only partially filled in."),
        EligibilityCheck(id="co_applicant_under_min_age", label="Co-applicant under minimum age", description="The co-applicant is younger than the minimum adult age."),
        EligibilityCheck(id="employment_requirement_not_met", label="Employment requirement not met", description="The household does not meet the configured employment requirement."),
        EligibilityCheck(id="future_employment_start", label="Future employment start", description="An employment start date is in the future."),
        EligibilityCheck(id="income_above_range", label="Income above range", description="Household gross income is above the allowed maximum."),
        EligibilityCheck(id="income_arithmetic_mismatch", label="Income arithmetic mismatch", description="The stated household income doesn't match the sum of the individual incomes."),
        EligibilityCheck(id="income_below_range", label="Income below range", description="Household gross income is below the required minimum."),
        EligibilityCheck(id="negative_number", label="Negative number", description="A numeric field (income, ages, counts) holds a negative value."),
        EligibilityCheck(id="owns_real_estate", label="Real estate ownership", description="The applicant reported owning real estate."),
        EligibilityCheck(id="too_few_children", label="Too few children", description="The household has fewer children than the minimum required."),
        EligibilityCheck(id="too_many_children", label="Too many children", description="The household has more children than the maximum allowed."),
    ],
    ai=[
        EligibilityCheck(id="pets_over_limit", label="Pet policy", description="The extracted pets exceed your dog, cat, or other-pet limits."),
        EligibilityCheck(id="placeholder_name", label="Placeholder name", description="A name field holds a placeholder or non-name."),
        EligibilityCheck(id="minimal_essay", label="Minimal essays", description="The application has no substantive response anywhere in its essay set."),
        EligibilityCheck(id="spam_essay", label="Spam essay", description="An essay is clearly spam or advertising rather than a genuine answer."),
        EligibilityCheck(id="ai_generated_essay", label="AI-generated essay", description="An essay reads as machine-generated rather than written by the applicant."),
        EligibilityCheck(id="internal_inconsistency", label="Internal inconsistency", description="The application contains a direct factual contradiction."),
        EligibilityCheck(id="fake_contact", label="Fake contact", description="A contact field contains a placeholder or keyboard-mash value."),
        EligibilityCheck(id="other", label="Other", description="The AI surfaced another concrete data-integrity concern."),
    ],
)
