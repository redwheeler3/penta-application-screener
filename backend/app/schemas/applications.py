"""Response shapes for the applications router.

Boundary models: the domain dataclasses (`app/domain/ranking.py`) and the stored
AI outputs (`app/ai/schemas.py`) stay snake_case and pure; these `*Out` models map
them to the camelCase wire. ``normalized`` and ``rawRow`` are intentionally
free-form dicts — their keys are raw form-field names (data like
``household_income``), not schema field names, so they pass through untouched.
"""

from typing import Any

from pydantic import Field

from app.schemas.base import RequestModel, ResponseModel
from app.schemas.openings import OpeningDetailsOut


class CommitteeOpeningOut(OpeningDetailsOut):
    phase: str


class HardFilterReason(ResponseModel):
    code: str
    message: str
    details: dict[str, Any] = {}


class Essay(ResponseModel):
    label: str
    question: str
    answer: str


class ScreeningFlagOut(ResponseModel):
    category: str
    summary: str
    evidence: str


class PetFactsOut(ResponseModel):
    """The pet inventory the screening AI extracted from the free-text pets field.
    Surfaced on the detail so the pet card can show the AI's ``reasoning`` — what it saw and
    how it classified it — at the finding, rather than making a member hunt the whole-pass
    narrative for the pet paragraph (extracting that slice would be brittle). The counts are
    what the deterministic pet rule judges. ``None`` when the app hasn't been screened."""

    dogs: int
    cats: int
    other_pets: list[str]
    reasoning: str


class DimensionContributionOut(ResponseModel):
    """Camel-cased view of the ranking ``DimensionContribution`` dataclass."""

    dimension_key: str
    name: str
    score: float
    weight: float
    impact: float
    confidence: str
    rationale: str
    evidence: str


class AIResultTraceOut(ResponseModel):
    """Provenance for one cached per-application model result. Cost and tokens describe
    its original generation allocation; a later run may reuse that result from cache."""

    model_id: str
    supports_reasoning_effort: bool
    reasoning_effort: str | None
    prompt_version: str
    input_tokens: int
    output_tokens: int
    cost_usd: float


class AIModelTraceOut(ResponseModel):
    """One exact model/reasoning pairing that contributed to a stored result."""

    model_id: str
    supports_reasoning_effort: bool
    reasoning_effort: str | None


class DimensionScoringTraceOut(ResponseModel):
    """Combined provenance for an applicant's current-dimension score results.

    A fresh scoring call commonly produces several dimension rows. On later updates,
    cached dimensions may originate from different calls, models, or prompt revisions,
    so this reports the exact total and all contributing provenance rather than
    pretending there was one call.
    """

    dimension_count: int
    models: list[AIModelTraceOut]
    prompt_versions: list[str]
    input_tokens: int
    output_tokens: int
    cost_usd: float


class ApplicationSummary(ResponseModel):
    id: int
    primary_email: str
    applicant_name: str | None = None
    co_applicant_name: str | None = None
    status: str
    status_source: str
    stale: bool
    hard_filter_reasons: list[HardFilterReason] = []
    child_count: int | None = None
    household_income: int | None = None
    # null = screening pass not run; int = flag count (0 = ran clean).
    flag_count: int | None = None
    flag_categories: list[str] | None = None
    # Whether the current member has starred (favourited) this applicant. Private
    # per member; a personal working aid with no effect on ranking or eligibility.
    starred_by_me: bool = False
    opening_ids: list[int] = []


class ApplicationDetail(ApplicationSummary):
    auto_status: str
    auto_status_source: str
    first_submitted_at: str | None = None
    last_submitted_at: str | None = None
    submission_version_count: int = 0
    normalized: dict[str, Any] | None = None
    essays: list[Essay] = []
    flags: list[ScreeningFlagOut] | None = None
    pet_facts: PetFactsOut | None = None
    raw_row: dict[str, Any] | None = None
    ai_narrative: str | None = None
    screening_trace: AIResultTraceOut | None = None
    dimension_scores: list[DimensionContributionOut] | None = None
    dimension_scoring_trace: DimensionScoringTraceOut | None = None
    # The current reviewer's private note. It is intentionally not part of the
    # application, source row, AI input, or any shared report.
    private_note: str = ""


class PrivateNoteUpdate(RequestModel):
    note: str = Field(max_length=10_000)


class ApplicationEnvelope(ResponseModel):
    """Single application is wrapped — it's an entity the SPA holds in state."""

    application: ApplicationDetail


class ApplicationListResponse(ResponseModel):
    # The whole pool, unpaginated; the client derives filters, sorting, and facet
    # counts (status/source/favourites) from it.
    applications: list[ApplicationSummary]
    openings: list[CommitteeOpeningOut]
