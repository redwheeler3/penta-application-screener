import time
from collections.abc import Iterator
from dataclasses import dataclass

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.ai.analysis import SpendingCapExceeded, enforce_cap
from app.ai.pricing import PassCost
from app.ai.provider import AIProvider
from app.ai.screening import (
    PassResult,
    applications_for_screening,
    estimate_screening,
    run_screening,
)
from app.api.dependencies import get_ai_provider, require_current_user
from app.api.problems import Problem
from app.db.models import User
from app.db.session import get_db
from app.schemas.events import (
    ItemErrorEvent,
    PhaseEvent,
    ProgressEvent,
    ScreeningSummary,
    emit,
)
from app.schemas.screening import ScreeningEstimateResponse
from app.schemas.settings import AppSettings
from app.services.cost_report import record_run_cost
from app.services.settings import get_app_settings

router = APIRouter(prefix="/screening", tags=["screening"])

# The single phase name for this one-pass job (rank uses criteria/scores).
PHASE = "screen"


@dataclass
class RunTally:
    """Running totals for a screening run, fed one screening result at a time
    and emitted as the final summary line.
    """

    analyzed: int = 0
    cached: int = 0
    flagged: int = 0
    failed: int = 0
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    # Sum of reused results' ORIGINAL cost — an estimate of what caching saved this run.
    cached_saved_usd: float = 0.0

    def add(self, result: PassResult) -> None:
        if result.failed:
            self.failed += 1
            return
        if result.outcome.cached:
            self.cached += 1
            # A cache hit spent nothing now; its stored cost is the original first-run
            # cost, so summing it estimates what regenerating would have cost.
            self.cached_saved_usd += result.outcome.cost_usd
        else:
            self.analyzed += 1
            self.cost_usd += result.outcome.cost_usd
            self.input_tokens += result.outcome.input_tokens
            self.output_tokens += result.outcome.output_tokens
        if result.outcome.output.flags:
            self.flagged += 1

    def as_pass_cost(self, model_id: str) -> PassCost:
        """The screening pass's spend in the shared shape (fresh tokens + cost, cache side)."""
        return PassCost(
            calls=self.analyzed,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            cost_usd=self.cost_usd,
            cached_count=self.cached,
            cached_saved_usd=self.cached_saved_usd,
            failed_calls=self.failed,
            model_id=model_id if self.analyzed else "",
        )


@router.get("/run/estimate", response_model=ScreeningEstimateResponse)
def estimate(
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> ScreeningEstimateResponse:
    settings: AppSettings = get_app_settings(db)
    result = estimate_screening(db, settings)
    estimated_usd = float(result["estimated_usd"])
    return ScreeningEstimateResponse(
        total=int(result["total"]),
        to_analyze=int(result["to_analyze"]),
        cached=int(result["cached"]),
        estimated_usd=estimated_usd,
        cap_usd=settings.ai.spending_cap_usd,
        within_cap=estimated_usd <= settings.ai.spending_cap_usd,
    )


@router.post("/run")
def run(
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
    provider: AIProvider = Depends(get_ai_provider),
) -> StreamingResponse:
    """Run the screening pass over the candidate applications, streaming progress.

    Responds as newline-delimited JSON (NDJSON): one ``{"type":"progress",...}``
    line per application as it finishes, then a final ``{"type":"summary",...}``
    line. The cap is enforced before streaming starts, so an over-cap run still
    fails fast with a 402.
    """
    settings: AppSettings = get_app_settings(db)

    estimate_result = estimate_screening(db, settings)

    # Block a no-op re-run: nothing uncached means every result is a cache hit
    # reproducing identical output. Mirrors the Rank chain's pool-fingerprint gate.
    if int(estimate_result["to_analyze"]) == 0:
        raise Problem(
            "unchanged_pool",
            detail="Screening is already up to date for these applicants. "
            "Sync new or changed applications before re-screening.",
        )

    try:
        enforce_cap(estimate_result, settings.ai.spending_cap_usd)
    except SpendingCapExceeded as exc:
        # 402 Payment Required: the run was blocked by the configured cap.
        raise Problem(
            "cap_exceeded",
            detail=str(exc),
            cap_usd=settings.ai.spending_cap_usd,
            estimated_usd=estimate_result["estimated_usd"],
        ) from exc

    applications = applications_for_screening(db)

    def stream() -> Iterator[str]:
        total = len(applications)
        tally = RunTally()
        yield emit(PhaseEvent(phase=PHASE, total=total))
        started = time.perf_counter()
        results = run_screening(
            db,
            provider,
            applications=applications,
            settings=settings,
            max_workers=settings.ai.max_workers,
        )
        for processed, result in enumerate(results, start=1):
            tally.add(result)
            if result.failed:
                # Surface the failed application (non-fatal), then keep streaming.
                yield emit(
                    ItemErrorEvent(
                        phase=PHASE,
                        application_id=result.application.id,
                        message=result.error,
                    )
                )
            yield emit(ProgressEvent(phase=PHASE, processed=processed, total=total))

        # Persist this run's cost + cache breakdown (the only point the fresh/cached
        # split is known). Screen is a single pass.
        record_run_cost(
            db,
            kind="screen",
            passes={"Screening": tally.as_pass_cost(settings.ai.screening_model)},
            durations_ms={"Screening": round((time.perf_counter() - started) * 1000)},
            estimated_usd=float(estimate_result["estimated_usd"]),
        )

        yield emit(
            ScreeningSummary(
                analyzed=tally.analyzed,
                cached=tally.cached,
                flagged=tally.flagged,
                failed=tally.failed,
                total_cost_usd=round(tally.cost_usd, 4),
            )
        )

    return StreamingResponse(stream(), media_type="application/x-ndjson")
