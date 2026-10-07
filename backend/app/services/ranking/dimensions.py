"""Stored ranking-dimension report parsing shared across ranking services."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.schemas import PoolDimensionReport
from app.db.models import Analysis, DimensionAlias
from app.services.ranking.identity import flatten_merges, report_aliases


def current_dimension_report(analysis: Analysis) -> PoolDimensionReport | None:
    """Parse the stored ``PoolDimensionReport`` from an analysis, if present."""
    if not analysis.dimension_report:
        return None
    return PoolDimensionReport.model_validate(analysis.dimension_report)


def alias_map(db: Session) -> dict[str, str]:
    """Every consolidation alias, resolved to its TERMINAL canonical key.

    Follows chains (A→B, B→C ⇒ A→C, B→C) so a later merge of a canonical key forwards
    the aliases already pointing at it. The post-score consolidation pass writes these;
    the match input resolves through them so a re-minted duplicate re-adopts the
    canonical key. Cycles (shouldn't occur — merges always point newer→older) are broken
    defensively by capping the walk.
    """
    return flatten_merges(_stored_aliases(db))


def report_alias_map(db: Session, report: PoolDimensionReport | None) -> dict[str, str]:
    """Resolve aliases against this report, retaining an intermediate survivor it owns."""
    return report_aliases(_stored_aliases(db), report)


def _stored_aliases(db: Session) -> dict[str, str]:
    return {alias.alias_key: alias.canonical_key for alias in db.scalars(select(DimensionAlias))}

