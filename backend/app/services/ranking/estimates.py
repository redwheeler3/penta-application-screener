"""Cost projections for ranking workflows.

Keeping these calculations outside the HTTP route makes their inputs, historical
fallbacks, and cache semantics easier to find and test independently.
"""

from typing import Any

from sqlalchemy.orm import Session

from app.ai.dimension_consolidation import estimate_consolidate
from app.ai.dimension_decomposition import estimate_decompose
from app.ai.dimension_discovery import eligible_applications, estimate_discovery
from app.ai.dimension_matching import estimate_match
from app.ai.dimension_scoring_cost import estimate_dimension_scoring
from app.ai.schemas import PoolDimension, PoolDimensionReport
from app.core.problems import Problem
from app.db.models import Application
from app.schemas.settings import AppSettings
from app.services.cost_report import recent_pass_fresh_usd
from app.services.ranking.analysis import get_current_analysis
from app.services.ranking.dimensions import current_dimension_report


def build_rank_estimate(
    db: Session,
    opening_id: int,
    settings: AppSettings,
    *,
    pool: list[Application] | None = None,
) -> dict[str, Any]:
    """Project the full Rank cost using recent actuals where they exist."""
    pool = pool if pool is not None else eligible_applications(db, opening_id)

    measured_discovery = recent_pass_fresh_usd(db, opening_id, "Pattern discovery")
    discovery_usd = (
        measured_discovery
        if measured_discovery is not None
        else estimate_discovery(pool, settings) * settings.ai.discovery_fan_out
    )

    measured_decompose = recent_pass_fresh_usd(db, opening_id, "Dimension decomposition")
    if measured_decompose is not None:
        decompose_usd = measured_decompose
    else:
        stub = PoolDimension(
            key="x",
            name="x",
            definition="x",
            high_end="x",
            low_end="x",
            why_it_differentiates="x",
        )
        projected = [
            PoolDimensionReport(dimensions=[stub] * 20)
            for _ in range(settings.ai.discovery_fan_out)
        ]
        decompose_usd = estimate_decompose(projected, settings)

    if get_current_analysis(db, opening_id) is None:
        match_usd = 0.0
    else:
        measured_match = recent_pass_fresh_usd(db, opening_id, "Dimension matching")
        match_usd = measured_match if measured_match is not None else estimate_match(settings)

    scoring_usd = estimate_dimension_scoring(
        db,
        opening_id,
        settings,
        include_coverage=False,
        candidates=pool,
    )["estimated_usd"]

    measured_consolidate = recent_pass_fresh_usd(
        db, opening_id, "Dimension consolidation"
    )
    consolidate_usd = (
        measured_consolidate
        if measured_consolidate is not None
        else estimate_consolidate(settings)
    )
    total = round(
        discovery_usd + decompose_usd + match_usd + scoring_usd + consolidate_usd,
        4,
    )
    return {
        "eligible": len(pool),
        "fan_out": settings.ai.discovery_fan_out,
        "breakdown": {
            "criteria_usd": round(discovery_usd + decompose_usd + consolidate_usd, 4),
            "match_usd": round(match_usd, 4),
            "scoring_usd": round(scoring_usd, 4),
        },
        "estimated_usd": total,
        "approximate": True,
    }


def current_scoring_estimate(
    db: Session,
    opening_id: int,
    settings: AppSettings,
) -> tuple[PoolDimensionReport, dict[str, object]]:
    """Return current criteria and the exact cache-aware score-only estimate."""
    analysis = get_current_analysis(db, opening_id)
    report = current_dimension_report(analysis) if analysis is not None else None
    if report is None:
        raise Problem(
            "run_required",
            detail="Discover ranking criteria before scoring applicants against them.",
        )
    return report, estimate_dimension_scoring(
        db, opening_id, settings, prefer_history=False
    )
