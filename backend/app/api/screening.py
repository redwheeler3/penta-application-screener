"""Screening API (milestone 7): pool pattern discovery and per-candidate
dimension scoring.

Flow the UI drives:
  1. POST /screening/discover  — one synthesis call over the eligible pool;
     persists a new ScreeningRun holding the discovered dimensions.
  2. GET  /screening/current   — the current run's dimensions + summary.
  3. GET  /screening/scoring/estimate — cost projection for scoring the pool
     against the current run's dimensions.
  4. POST /screening/scoring/run — scores every eligible applicant, streaming
     progress as NDJSON (same shape as the essay-analysis run).

Discovery is not cap-gated (a single call is cheap and the cap is a per-batch
projection); scoring is cap-gated before streaming, like the other batch passes.
"""

import json
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.ai.analysis import ScreeningResult, SpendingCapExceeded, enforce_cap
from app.ai.dimension_scoring import (
    applications_to_score,
    estimate_dimension_scoring,
    screen_dimension_scores,
)
from app.ai.pattern_discovery import discover_patterns, eligible_applications
from app.ai.provider import AIProvider
from app.api.dependencies import get_ai_provider, require_current_user
from app.db.models import User
from app.db.session import get_db
from app.schemas.settings import AppSettings
from app.services.screening_run import (
    create_run,
    current_pattern_report,
    get_current_run,
)
from app.services.settings import get_app_settings

router = APIRouter(prefix="/screening", tags=["screening"])


@dataclass
class RunTally:
    """Running totals for a scoring run, emitted as the final summary line."""

    analyzed: int = 0
    cached: int = 0
    failed: int = 0
    cost_usd: float = 0.0

    def add(self, result: ScreeningResult) -> None:
        if result.failed:
            self.failed += 1
            return
        if result.outcome.cached:
            self.cached += 1
        else:
            self.analyzed += 1
        self.cost_usd += result.outcome.cost_usd


def _run_payload(db: Session) -> dict[str, Any] | None:
    """The current run's discovered pattern report, shaped for the UI."""
    run = get_current_run(db)
    if run is None:
        return None
    report = current_pattern_report(run)
    if report is None:
        return None
    return {
        "runId": run.id,
        "name": run.name,
        "status": run.status,
        "summary": report.summary,
        "dimensions": report.model_dump(mode="json")["dimensions"],
    }


@router.post("/discover")
def discover(
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
    provider: AIProvider = Depends(get_ai_provider),
) -> dict[str, Any]:
    """Discover the pool's differentiating dimensions and start a screening run.

    One synthesis call over the eligible pool. Requires at least one eligible
    applicant. Each call creates a fresh run (the current run is the latest).
    """
    settings: AppSettings = get_app_settings(db)
    applications = eligible_applications(db)
    if not applications:
        raise HTTPException(status_code=409, detail="No eligible applications to analyze.")

    # The synthesis-model call is the one place a Bedrock/network failure can
    # surface here. Wrap it so the client gets a readable 502 (the same shape as
    # /sync) instead of a bare 500 with the traceback only in the server log.
    try:
        report, narrative, cost = discover_patterns(
            db, provider, applications=applications, settings=settings
        )
    except Exception as exc:  # noqa: BLE001 — surface any provider failure to the UI
        raise HTTPException(
            status_code=502,
            detail=f"Pattern discovery failed calling the AI model: {type(exc).__name__}: {exc}",
        ) from exc

    create_run(
        db,
        report=report,
        model_id=settings.ai.synthesis_model,
        narrative=narrative,
        cost_usd=cost,
    )
    return _run_payload(db)


@router.get("/current")
def current(
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any] | None:
    """The current screening run's dimensions, or null if none discovered yet."""
    return _run_payload(db)


@router.get("/scoring/estimate")
def scoring_estimate(
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    settings: AppSettings = get_app_settings(db)
    run = get_current_run(db)
    report = current_pattern_report(run) if run is not None else None
    if report is None:
        raise HTTPException(status_code=409, detail="Discover patterns before scoring.")

    result = estimate_dimension_scoring(db, report, settings)
    result["cap_usd"] = settings.ai.spending_cap_usd
    result["within_cap"] = float(result["estimated_usd"]) <= settings.ai.spending_cap_usd
    return result


@router.post("/scoring/run")
def scoring_run(
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
    provider: AIProvider = Depends(get_ai_provider),
) -> StreamingResponse:
    """Score every eligible applicant against the current run's dimensions,
    streaming progress as NDJSON (one progress line per applicant, then a
    summary). The cap is enforced before streaming starts, so an over-cap run
    fails fast with a 402. Informational — never changes status.
    """
    settings: AppSettings = get_app_settings(db)
    run = get_current_run(db)
    report = current_pattern_report(run) if run is not None else None
    if report is None:
        raise HTTPException(status_code=409, detail="Discover patterns before scoring.")

    estimate_result = estimate_dimension_scoring(db, report, settings)
    try:
        enforce_cap(estimate_result, settings.ai.spending_cap_usd)
    except SpendingCapExceeded as exc:
        raise HTTPException(status_code=402, detail=str(exc)) from exc

    applications = applications_to_score(db)

    def stream() -> Iterator[str]:
        total = len(applications)
        tally = RunTally()
        results = screen_dimension_scores(
            db,
            provider,
            applications=applications,
            report=report,
            settings=settings,
            max_workers=settings.ai.max_workers,
        )
        for processed, result in enumerate(results, start=1):
            tally.add(result)
            if result.failed:
                yield json.dumps(
                    {
                        "type": "error",
                        "applicationId": result.application.id,
                        "message": result.error,
                    }
                ) + "\n"
            yield json.dumps(
                {"type": "progress", "processed": processed, "total": total}
            ) + "\n"

        yield json.dumps(
            {
                "type": "summary",
                "analyzed": tally.analyzed,
                "cached": tally.cached,
                "failed": tally.failed,
                "totalCostUsd": round(tally.cost_usd, 4),
            }
        ) + "\n"

    return StreamingResponse(stream(), media_type="application/x-ndjson")
