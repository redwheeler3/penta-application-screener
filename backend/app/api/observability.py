"""The Observability-tab read endpoints: cumulative spend, the latest Screen/Rank runs, and
operational trends across all completed runs. No model calls — each is a
straight projection over the persisted run-cost ledger. Top-level (not under ``/ranking``)
because these span every run kind — Screen, Rank, and score-current — not ranking alone.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import require_current_user
from app.db.models import User
from app.db.session import get_db
from app.schemas.observability import CostReport, LastRunsReport, MetricsReport
from app.services.cost_report import cost_report, last_runs_report
from app.services.metrics import metrics_report

router = APIRouter(prefix="/observability", tags=["observability"])


@router.get("/cost", response_model=CostReport)
def observability_cost(
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> CostReport:
    """Cumulative AI spend for the Observability tab, grouped by run."""
    return cost_report(db)


@router.get("/last-runs", response_model=LastRunsReport)
def observability_last_runs(
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> LastRunsReport:
    """The most recent Screen and Rank runs, each with fresh spend + cache savings."""
    return last_runs_report(db)


@router.get("/metrics", response_model=MetricsReport)
def observability_metrics(
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> MetricsReport:
    """Operational trends across all completed runs — cost/tokens/latency/cache-hit/
    failures per run and per pass, plus dimension count over time."""
    return metrics_report(db)
