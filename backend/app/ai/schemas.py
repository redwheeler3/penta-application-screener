"""Structured output schemas — the shared contract between prompts, storage, the
API, and the UI for AI-assisted screening. One definition per shape keeps prompts,
caching, and rendering aligned.
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
    """Neutral, factual extraction across a candidate's four essays (see SPEC "Essay
    Analysis").

    Describes WHAT the applicant said, never how good it is — evaluation is the
    ranker's job. An additive digest: the raw essays are preserved, so off-question
    content stays available. ``str | None`` fields are prose-or-absent; ``list``
    fields are empty when nothing was said — both forms of "did not say" are signal
    the ranker may read.
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


# --- Pattern discovery and dimension scoring --------------------------------
#
# The LLM extracts scored features; ranking is deterministic math over them.
# Discovery finds how THIS pool varies; scoring rates each candidate on those
# dimensions. Both schemas have a fixed SHAPE; only which dimensions appear is open.


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
    from_committee_request: bool = Field(
        default=False,
        description=(
            "Set true ONLY for a dimension you created in response to a committee "
            "request (a favourited or proposed axis the prompt asked you to "
            "consider). A dimension you discovered on your own stays false. If one "
            "request splits into several dimensions, mark each of them true."
        ),
    )


class PoolPatternReport(BaseModel):
    """Pool-level discovery: the differentiating dimensions for THIS pool.

    Run-scoped, not per-candidate. It does not rank, score, or weight anyone —
    importance is the committee's call. Scoring rates each applicant against these
    dimensions; ranking is deterministic math on top.
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
        description=(
            "How well the evidence pins down the applicant's TRUE standing on "
            "this dimension — not how sure you are about what they wrote. A "
            "dimension the applicant did not address is LOW confidence even when "
            "you are certain it went unmentioned: silence is weak evidence, since "
            "they may have the strength and simply not have stated it."
        ),
    )


class DimensionScoringReport(BaseModel):
    """One candidate scored against the run's discovered dimensions — exactly one
    DimensionScore per dimension. Informational; never touches status. The scores
    are the support for ranking, behind committee-facing labels and rationale.
    """

    scores: list[DimensionScore] = Field(
        default_factory=list,
        description="One entry per discovered dimension, scoring this candidate on it.",
    )


class DimensionMatch(BaseModel):
    """One identity match between a freshly-discovered dimension and a prior one.

    On a re-rank, maps each NEW dimension onto the prior dimension it is the *same
    concept* as, so tier placement and cached scores carry forward. A pure identity
    judgment, never a weighting. High bar: match only when they mean the same thing.
    """

    new_key: str = Field(
        description="The key of a dimension in the NEW (just-discovered) set.",
    )
    old_key: str = Field(
        description=(
            "The key of the PRIOR-run dimension that means the same thing as "
            "new_key. Only include a pair when they are clearly the same concept."
        ),
    )


class DimensionMatchReport(BaseModel):
    """The high-confidence identity matches from new dimensions to prior ones,
    strictly one-to-one. Unmatched new dimensions are absent — they start in Ignore
    for the committee to triage. Absence is safe (a missed match costs a re-drag; a
    wrong match would move tier intent onto the wrong concept).
    """

    matches: list[DimensionMatch] = Field(
        default_factory=list,
        description=(
            "High-confidence identity matches only. Omit any new dimension you are "
            "not confident maps to a specific prior dimension."
        ),
    )
