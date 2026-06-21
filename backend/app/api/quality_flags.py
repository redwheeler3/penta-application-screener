import json
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.ai.analysis import SpendingCapExceeded, enforce_cap
from app.ai.provider import AIProvider
from app.ai.quality_flags import (
    ScreeningResult,
    applications_to_analyze,
    estimate_quality_flags,
    screen_quality_flags,
)
from app.ai.strands_provider import StrandsProvider
from app.api.dependencies import require_current_user
from app.db.models import User
from app.db.session import get_db
from app.schemas.settings import AppSettings
from app.services.settings import get_app_settings

router = APIRouter(prefix="/quality-flags", tags=["quality-flags"])


@dataclass
class RunTally:
    """Running totals for a quality-flag run, fed one screening result at a time
    and emitted as the final summary line.
    """

    analyzed: int = 0
    cached: int = 0
    flagged: int = 0
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
        if result.outcome.output.flags:
            self.flagged += 1


def get_ai_provider(db: Session = Depends(get_db)) -> AIProvider:
    """Real Bedrock-backed provider. Overridden in tests with a MockProvider."""
    settings = get_app_settings(db)
    # Size the connection pool to the worker count so concurrent screening calls
    # don't queue on sockets.
    return StrandsProvider(
        region=settings.ai.region,
        max_pool_connections=settings.ai.max_workers,
    )


@router.get("/estimate")
def estimate(
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    settings: AppSettings = get_app_settings(db)
    result = estimate_quality_flags(db, settings)
    result["cap_usd"] = settings.ai.spending_cap_usd
    result["within_cap"] = float(result["estimated_usd"]) <= settings.ai.spending_cap_usd
    return result


@router.post("/run")
def run(
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
    provider: AIProvider = Depends(get_ai_provider),
) -> StreamingResponse:
    """Run quality flags over the candidate applications, streaming progress.

    Responds as newline-delimited JSON (NDJSON): one ``{"type":"progress",...}``
    line per application as it finishes, then a final ``{"type":"summary",...}``
    line. The cap is enforced before streaming starts, so an over-cap run still
    fails fast with a 402.
    """
    settings: AppSettings = get_app_settings(db)

    estimate_result = estimate_quality_flags(db, settings)
    try:
        enforce_cap(estimate_result, settings.ai.spending_cap_usd)
    except SpendingCapExceeded as exc:
        # 402 Payment Required: the run was blocked by the configured cap.
        raise HTTPException(status_code=402, detail=str(exc)) from exc

    applications = applications_to_analyze(db)

    def stream() -> Iterator[str]:
        total = len(applications)
        tally = RunTally()
        results = screen_quality_flags(
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
                {"type": "progress", "processed": processed, "total": total, "flagged": tally.flagged}
            ) + "\n"

        yield json.dumps(
            {
                "type": "summary",
                "analyzed": tally.analyzed,
                "cached": tally.cached,
                "flagged": tally.flagged,
                "failed": tally.failed,
                "totalCostUsd": round(tally.cost_usd, 4),
            }
        ) + "\n"

    return StreamingResponse(stream(), media_type="application/x-ndjson")
