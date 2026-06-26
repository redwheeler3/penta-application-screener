"""Response/request shapes for the ranking router (formerly /screening).

Reuses the applications boundary out-models (`DimensionContributionOut`) for the
ranked candidates, so the ranked-list row and the candidate-detail contributions
share one wire shape. ``PoolDimensionOut`` is a camelCase view of the stored
``PoolDimension`` (which stays snake_case as the prompt/storage contract).
"""

from app.schemas.applications import DimensionContributionOut
from app.schemas.base import RequestModel, ResponseModel


class PoolDimensionOut(ResponseModel):
    """Camel-cased view of a stored discovery dimension."""

    key: str
    name: str
    definition: str
    why_it_differentiates: str
    from_committee_request: bool = False


class CurrentRunResponse(ResponseModel):
    """GET /ranking/current — the current run's discovered criteria, or null."""

    run_id: int
    name: str
    status: str
    summary: str
    dimensions: list[PoolDimensionOut]
    new_dimension_keys: list[str] = []
    favourited_keys: list[str] = []
    proposed_dimensions: list[str] = []


class RankEstimateBreakdown(ResponseModel):
    essays_usd: float
    criteria_usd: float
    match_usd: float
    scoring_usd: float


class RankEstimateResponse(ResponseModel):
    """GET /ranking/estimate — combined cost projection for the rank chain."""

    eligible: int
    breakdown: RankEstimateBreakdown
    essays_cached: int
    estimated_usd: float
    approximate: bool
    cap_usd: float
    within_cap: bool
    ranking_current: bool


class RankedCandidateOut(ResponseModel):
    """Camel-cased view of the ranking ``RankedCandidate`` dataclass."""

    application_id: int
    name: str | None = None
    rank: int
    fit: float
    band: str
    contributions: list[DimensionContributionOut]


class RankingResponse(ResponseModel):
    """GET /ranking and PUT /ranking/tiers — the ranked shortlist for the run."""

    run_id: int
    weights: dict[str, float]  # keyed by dimension key (data)
    scored_count: int
    candidates: list[RankedCandidateOut]
    new_dimension_keys: list[str] = []
    favourited_keys: list[str] = []
    proposed_dimensions: list[str] = []


class TierOut(ResponseModel):
    id: str
    label: str
    dimension_keys: list[str] = []
    ignore: bool = False


class TiersResponse(ResponseModel):
    """GET /ranking/tiers — the committee's importance-tier layout."""

    tiers: list[TierOut]


class SeedsResponse(ResponseModel):
    """PUT /ranking/seeds — the current discovery seed state."""

    favourited_keys: list[str] = []
    proposed_dimensions: list[str] = []


# --- Request bodies (camelCase-only on the wire) ----------------------------


class TierModel(RequestModel):
    id: str
    label: str
    dimension_keys: list[str] = []
    ignore: bool = False


class TierLayoutUpdate(RequestModel):
    tiers: list[TierModel]
    # Keys the committee acknowledged as "reviewed" this save (badge ✕ / "mark all
    # reviewed") — they drop out of new_dimension_keys even if left in Ignore.
    acknowledged_keys: list[str] = []


class SeedsUpdate(RequestModel):
    # Both optional so the UI can update one without clobbering the other.
    favourited_keys: list[str] | None = None
    proposed_dimensions: list[str] | None = None
