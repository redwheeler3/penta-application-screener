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
