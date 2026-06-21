"""Structured output schemas — the shared contract between prompts, storage,
the API, and the UI for AI-assisted screening.

Milestone 5 (AI quality flags) uses ``QualityFlagReport``. Later milestones
(essay analysis, ranking) will add their own schemas here so prompts, caching,
and rendering stay aligned to one definition.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class FlagCategory(StrEnum):
    PLACEHOLDER_NAME = "placeholder_name"
    SUSPICIOUS_NAME = "suspicious_name"
    MINIMAL_ESSAY = "minimal_essay"
    SPAM_ESSAY = "spam_essay"
    AI_GENERATED_ESSAY = "ai_generated_essay"
    DUPLICATED_ANSWERS = "duplicated_answers"
    INTERNAL_INCONSISTENCY = "internal_inconsistency"
    FAKE_CONTACT = "fake_contact"
    PET_POLICY = "pet_policy"
    OTHER = "other"


class FlagSeverity(StrEnum):
    INFO = "info"
    NOTABLE = "notable"


class QualityFlag(BaseModel):
    category: FlagCategory
    severity: FlagSeverity = Field(
        description="info for minor notes; notable for things the screener should review",
    )
    summary: str = Field(description="One-sentence, neutral description of the concern.")
    evidence: str = Field(
        description="Short quote or specific field reference supporting the flag. No full essays.",
    )


class QualityFlagReport(BaseModel):
    """The complete set of informational quality flags for one application.

    Empty ``flags`` means the integrity pass found nothing of concern. Flags are
    never disqualifying — they only surface things for the screener to review.
    """

    flags: list[QualityFlag] = Field(default_factory=list)


class EssayAnalysisReport(BaseModel):
    """Neutral, factual extraction across a candidate's four essays.

    One field per thing the form's essay questions ask for (see SPEC "Essay
    Analysis"). This describes WHAT the applicant said, never how good it is —
    evaluation against committee criteria is the milestone 7 ranker's job, and
    those criteria are discovered there, so this pass must not pre-commit
    judgment. The raw essays are preserved alongside this, so this is an additive
    digest, not a replacement: anything off-question stays available to the
    ranker from the source.

    ``str | None`` fields are prose-or-absent; ``list`` fields are empty when the
    applicant said nothing of that kind. Both forms of "did not say" are real
    signal the ranker may read; this pass does not judge the absence.
    """

    summary: str = Field(
        description=(
            "A 2-4 sentence neutral, factual digest across all four essays. "
            "Describe what the applicant conveyed; do not evaluate fit, "
            "commitment, or quality, and do not speculate."
        )
    )
    household_context: str | None = Field(
        default=None,
        description="Who is in the household, as the applicant introduced them (Q1). Null if not stated.",
    )
    employment_background: str | None = Field(
        default=None,
        description="Work situation as narrated, applicant and co-applicant (Q1). Null if not stated.",
    )
    interests: list[str] = Field(
        default_factory=list,
        description="Interests the applicant stated (Q1).",
    )
    values: list[str] = Field(
        default_factory=list,
        description="Values the applicant expressed (Q1).",
    )
    skills_offered: list[str] = Field(
        default_factory=list,
        description="Concrete skills offered to help run or maintain the co-op, applicant and co-applicant (Q2).",
    )
    prior_co_op_experience: str | None = Field(
        default=None,
        description="Prior co-op experience the applicant or co-applicant stated (Q3). Null if none given.",
    )
    stated_motivations: list[str] = Field(
        default_factory=list,
        description="Reasons the applicant gave for wanting to live in a co-op (Q4).",
    )
    stated_contributions: list[str] = Field(
        default_factory=list,
        description="Ways the applicant said they would be a valuable member (Q4).",
    )
    evidence: list[str] = Field(
        default_factory=list,
        description="Short direct quotes or field references grounding the extractions above. No full essays.",
    )
