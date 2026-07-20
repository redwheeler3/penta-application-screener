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
    prompt_version: str
    input_tokens: int
    output_tokens: int
    cost_usd: float


class DimensionScoringTraceOut(ResponseModel):
    """Combined provenance for an applicant's current-dimension score results.

    A fresh scoring call commonly produces several dimension rows. On later updates,
    cached dimensions may originate from different calls, models, or prompt revisions,
    so this reports the exact total and all contributing provenance rather than
    pretending there was one call.
    """

    dimension_count: int
    model_ids: list[str]
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
    created_at: str | None = None


class ApplicationDetail(ApplicationSummary):
    auto_status: str
    auto_status_source: str
    normalized: dict[str, Any] | None = None
    essays: list[Essay] = []
    flags: list[ScreeningFlagOut] | None = None
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


class Facets(ResponseModel):
    # Keyed by enum values (data): {eligible, ineligible}, {untouched, rules, ...}.
    status: dict[str, int]
    source: dict[str, int]


class ApplicationListResponse(ResponseModel):
    applications: list[ApplicationSummary]
    total: int
    page: int
    page_size: int
    facets: Facets
