"""Response shape for the screening (Screen step) estimate."""

from app.schemas.base import ResponseModel


class ScreeningEstimateResponse(ResponseModel):
    """GET /screening/estimate — the pre-run cost projection + cap check."""

    total: int
    to_analyze: int
    cached: int
    estimated_usd: float
    cap_usd: float
    within_cap: bool
