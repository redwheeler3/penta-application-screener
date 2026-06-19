import json
from collections.abc import Iterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.ai.analysis import SpendingCapExceeded, enforce_cap
from app.ai.provider import AIProvider
from app.ai.quality_flags import (
    analyze_one,
    eligible_applications,
    estimate_quality_flags,
)
from app.ai.strands_provider import StrandsProvider
from app.api.dependencies import require_admin
from app.db.models import User
from app.db.session import get_db
from app.schemas.settings import AppSettings
from app.services.settings import get_app_settings

router = APIRouter(prefix="/quality-flags", tags=["quality-flags"])


def get_ai_provider(db: Session = Depends(get_db)) -> AIProvider:
    """Real Bedrock-backed provider. Overridden in tests with a MockProvider."""
    settings = get_app_settings(db)
    return StrandsProvider(region=settings.ai.region)


@router.get("/estimate")
def estimate(
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    settings: AppSettings = get_app_settings(db)
    result = estimate_quality_flags(db, settings)
    result["cap_usd"] = settings.ai.spending_cap_usd
    result["within_cap"] = float(result["estimated_usd"]) <= settings.ai.spending_cap_usd
    return result


@router.post("/run")
def run(
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
    provider: AIProvider = Depends(get_ai_provider),
) -> StreamingResponse:
    """Run quality flags over eligible applications, streaming progress.

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

    applications = eligible_applications(db)

    def stream() -> Iterator[str]:
        total = len(applications)
        analyzed = cached = flagged = 0
        total_cost = 0.0
        for index, application in enumerate(applications, start=1):
            outcome = analyze_one(db, provider, application=application, settings=settings)
            if outcome.cached:
                cached += 1
            else:
                analyzed += 1
            total_cost += outcome.cost_usd
            if outcome.output.flags:
                flagged += 1
            yield json.dumps(
                {"type": "progress", "processed": index, "total": total, "flagged": flagged}
            ) + "\n"

        yield json.dumps(
            {
                "type": "summary",
                "analyzed": analyzed,
                "cached": cached,
                "flagged": flagged,
                "totalCostUsd": round(total_cost, 4),
            }
        ) + "\n"

    return StreamingResponse(stream(), media_type="application/x-ndjson")
