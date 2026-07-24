"""The Insights-tab read endpoints: cumulative spend, the latest Screen/Rank runs, and
operational trends across all completed runs (M13 Pillars 1 + 3). No model calls — each is a
straight projection over the persisted run-cost ledger. Top-level (not under ``/ranking``)
because these span every run kind — Screen, Rank, and score-current — not ranking alone.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import require_current_user
from app.db.models import User
from app.db.session import get_db
from app.schemas.insights import CostReport, LastRunsReport, MetricsReport
from app.services.cost_report import cost_report, last_runs_report
from app.services.metrics import metrics_report

router = APIRouter(prefix="/insights", tags=["insights"])


@router.get("/cost", response_model=CostReport)
def insights_cost(
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> CostReport:
    """Cumulative AI spend for the Insights tab, grouped by run (M13 Pillar 1)."""
    return cost_report(db)


@router.get("/last-runs", response_model=LastRunsReport)
def insights_last_runs(
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> LastRunsReport:
    """The most recent Screen and Rank runs, each with fresh spend + cache savings."""
    return last_runs_report(db)


@router.get("/metrics", response_model=MetricsReport)
def insights_metrics(
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> MetricsReport:
    """Operational trends across all completed runs — cost/tokens/latency/cache-hit/
    failures per run and per pass, plus dimension count over time (M13 Pillar 3)."""
    return metrics_report(db)
