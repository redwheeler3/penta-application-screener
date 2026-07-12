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
    dimension_scores: list[DimensionContributionOut] | None = None


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
