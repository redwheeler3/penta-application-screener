"""Response shapes for the applications router.

Boundary models: the domain dataclasses (`app/domain/ranking.py`) and the stored
AI outputs (`app/ai/schemas.py`) stay snake_case and pure; these `*Out` models map
them to the camelCase wire. ``normalized`` and ``rawRow`` are intentionally
free-form dicts — their keys are raw form-field names (data like
``household_income``), not schema field names, so they pass through untouched.
"""

from typing import Any

from app.schemas.base import ResponseModel


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
    severity: str
    summary: str
    evidence: str


class EssayAnalysisOut(ResponseModel):
    """Camel-cased view of the stored ``EssayAnalysisReport`` (which stays
    snake_case as the prompt/storage contract)."""

    summary: str
    household_context: str | None = None
    employment_background: str | None = None
    interests: list[str] = []
    values: list[str] = []
    skills_offered: list[str] = []
    prior_co_op_experience: str | None = None
    stated_motivations: list[str] = []
    stated_contributions: list[str] = []
    evidence: list[str] = []


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


class AITracePassOut(ResponseModel):
    """One pass's AI-call trace metadata for a candidate (M13 per-application
    legibility). Operator detail — model, prompt version, tokens, cost — surfaced in
    a collapsed panel, kept off the committee's decision content.

    ``calls`` is 1 for the once-per-candidate passes (screening, essay analysis) and N
    for dimension scoring (one row per dimension), whose tokens/cost are summed. When a
    rolled-up pass spans more than one prompt version, ``prompt_version`` is null and
    ``mixed_versions`` is true — the tell that a re-rank re-scored only some dimensions.
    """

    pass_label: str  # "Screening", "Essay analysis", "Dimension scoring"
    model_id: str
    prompt_version: str | None = None
    mixed_versions: bool = False
    calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: float


class AITraceOut(ResponseModel):
    """The candidate's AI-call trace across all passes, plus the summed total."""

    passes: list[AITracePassOut]
    total_cost_usd: float
    total_tokens: int


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
    essay_analysis: EssayAnalysisOut | None = None
    dimension_scores: list[DimensionContributionOut] | None = None
    # Per-pass AI-call trace (model/version/tokens/cost), for the collapsed operator
    # panel. null when the candidate has no AI results yet.
    ai_trace: AITraceOut | None = None


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
