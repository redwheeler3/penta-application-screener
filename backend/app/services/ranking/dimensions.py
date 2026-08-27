"""Stored ranking-dimension report parsing shared across ranking services."""

from app.ai.schemas import PoolDimensionReport
from app.db.models import Analysis


def current_dimension_report(analysis: Analysis) -> PoolDimensionReport | None:
    """Parse the stored ``PoolDimensionReport`` from an analysis, if present."""
    if not analysis.dimension_report:
        return None
    return PoolDimensionReport.model_validate(analysis.dimension_report)


