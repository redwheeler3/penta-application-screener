"""Structured output schemas — the shared contract between prompts, storage,
the API, and the UI for AI-assisted screening.

Milestone 5 (AI quality flags) uses ``QualityFlagReport``; milestone 6 added
``EssayAnalysisReport``; milestone 7 added ``PoolPatternReport`` and
``DimensionScoringReport``. Each milestone's schemas live here so prompts,
caching, and rendering stay aligned to one definition.
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


# --- Pattern discovery and dimension scoring (milestone 7) ------------------
#
# The LLM extracts scored features; ranking (milestone 8) is deterministic math
# over them. The Pattern Finder discovers how THIS pool varies; the scoring pass
# rates each candidate on those discovered dimensions. Both schemas have a fixed
# SHAPE; only which dimensions appear is open — the same discipline as
# EssayAnalysisReport (see SPEC "Pattern Discovery And Dimension Scoring").


class PoolDimension(BaseModel):
    """One discovered axis along which this applicant pool meaningfully varies."""

    key: str = Field(
        description=(
            "Stable snake_case identifier, e.g. 'participation_commitment'. "
            "Used to tie each candidate's score back to this dimension, so it "
            "must be unique within the report and stable wording."
        )
    )
    name: str = Field(description="Short human-readable label for the committee UI.")
    definition: str = Field(
        description="1-2 sentences defining what this dimension measures, in neutral terms.",
    )
    why_it_differentiates: str = Field(
        description=(
            "Briefly, why this dimension actually separates THIS pool — what "
            "varies across candidates here, not a generic ideal."
        )
    )
    default_weight: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "Proposed starting importance toward 'fit for Penta', 0..1. The "
            "committee re-weights these later; this is only a default."
        ),
    )


class PoolPatternReport(BaseModel):
    """Pool-level discovery: the differentiating dimensions for THIS pool.

    Run-scoped, not per-candidate — it describes how the pool varies and proposes
    a default weighting. It does not rank or score anyone; the per-candidate
    scoring pass rates each applicant against these dimensions, and ranking is
    deterministic math layered on top (milestone 8).
    """

    summary: str = Field(
        description=(
            "2-4 sentences on what most distinguishes strong from weak fit "
            "across this specific pool. Neutral, committee-facing."
        )
    )
    dimensions: list[PoolDimension] = Field(
        default_factory=list,
        description=(
            "The discovered dimensions. Keep to the few that genuinely "
            "differentiate this pool — not an exhaustive rubric."
        ),
    )


class ScoreConfidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class DimensionScore(BaseModel):
    """One candidate's score on one discovered dimension, with grounding."""

    dimension_key: str = Field(
        description="The PoolDimension.key this score is for. Must match a discovered dimension.",
    )
    score: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "How strongly this candidate exhibits the dimension, 0..1, judged "
            "only on stated evidence. Absence of evidence is a low score, not a "
            "guess."
        ),
    )
    rationale: str = Field(
        description="One neutral sentence explaining the score from what the applicant said.",
    )
    evidence: str = Field(
        description="Short quote or field reference grounding the score. No full essays. Empty if nothing stated.",
    )
    confidence: ScoreConfidence = Field(
        description="How well-supported this score is by the available text.",
    )


class DimensionScoringReport(BaseModel):
    """One candidate scored against the run's discovered dimensions.

    Fixed shape, open contents: exactly one DimensionScore per discovered
    dimension. Informational like essay analysis — never touches eligibility
    status. The scores are the hidden support for ranking; the committee-facing
    UI emphasizes labels, rationale, and evidence over the raw numbers.
    """

    scores: list[DimensionScore] = Field(
        default_factory=list,
        description="One entry per discovered dimension, scoring this candidate on it.",
    )
