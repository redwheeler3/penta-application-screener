import json
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.ai.analysis import ScreeningResult, SpendingCapExceeded, enforce_cap
from app.ai.essay_analysis import (
    applications_to_analyze,
    estimate_essay_analysis,
    screen_essays,
)
from app.ai.provider import AIProvider
from app.api.dependencies import get_ai_provider, require_current_user
from app.db.models import User
from app.db.session import get_db
from app.schemas.settings import AppSettings
from app.services.settings import get_app_settings

router = APIRouter(prefix="/essay-analysis", tags=["essay-analysis"])


@dataclass
class RunTally:
    """Running totals for an essay-analysis run, fed one result at a time and
    emitted as the final summary line. Essay analysis is informational, so there
    is no flagged/status count — just analyzed/cached/failed and cost.
    """

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


@router.get("/estimate")
def estimate(
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    settings: AppSettings = get_app_settings(db)
    result = estimate_essay_analysis(db, settings)
    result["cap_usd"] = settings.ai.spending_cap_usd
    result["within_cap"] = float(result["estimated_usd"]) <= settings.ai.spending_cap_usd
    return result


@router.post("/run")
def run(
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
    provider: AIProvider = Depends(get_ai_provider),
) -> StreamingResponse:
    """Run essay analysis over the eligible applications, streaming progress.

    Responds as newline-delimited JSON (NDJSON): one ``{"type":"progress",...}``
    line per application as it finishes, then a final ``{"type":"summary",...}``
    line. The cap is enforced before streaming starts, so an over-cap run still
    fails fast with a 402. This pass is informational and never changes status.
    """
    settings: AppSettings = get_app_settings(db)

    estimate_result = estimate_essay_analysis(db, settings)
    try:
        enforce_cap(estimate_result, settings.ai.spending_cap_usd)
    except SpendingCapExceeded as exc:
        # 402 Payment Required: the run was blocked by the configured cap.
        raise HTTPException(status_code=402, detail=str(exc)) from exc

    applications = applications_to_analyze(db)

    def stream() -> Iterator[str]:
        total = len(applications)
        tally = RunTally()
        results = screen_essays(
            db,
            provider,
            applications=applications,
            settings=settings,
            max_workers=settings.ai.max_workers,
        )
        for processed, result in enumerate(results, start=1):
            tally.add(result)
            if result.failed:
                # Surface the failed application, then keep streaming the rest.
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
