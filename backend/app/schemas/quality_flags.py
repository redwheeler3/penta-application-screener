"""Response shape for the quality-flags (Screen) estimate."""

from app.schemas.base import ResponseModel


class QualityFlagEstimate(ResponseModel):
    """GET /quality-flags/estimate — the pre-run cost projection + cap check."""

    total: int
    to_analyze: int
    cached: int
    estimated_usd: float
    cap_usd: float
    within_cap: bool
