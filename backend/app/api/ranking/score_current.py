"""Fill missing scores for the current criteria without creating a new analysis."""

import time
from collections.abc import Iterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.ai.analysis import SpendingCapExceeded, enforce_cap
from app.ai.dimension_scoring import (
    applications_needing_scores,
    applications_to_score,
    score_dimensions,
)
from app.ai.provider import AIProvider
from app.api.dependencies import get_ai_provider, require_current_user
from app.core.problems import Problem
from app.db.models import User
from app.db.session import get_db
from app.schemas.events import PhaseEvent, ProgressEvent, RankSummary, emit
from app.schemas.ranking import ScoreCurrentEstimateResponse
from app.services.applications.scope import resolve_visible_opening_id
from app.services.cost_report import SCORE_CURRENT_KIND, record_run_cost
from app.services.openings.selection import require_ai_actions_available
from app.services.ranking.analysis import get_current_analysis, record_rank_inputs
from app.services.ranking.estimates import current_scoring_estimate
from app.services.ranking.freshness import rank_inputs_fingerprint
from app.services.ranking.pipeline import SCORES, ScoreTally
from app.services.run_lock import acquire_run_lock, release_run_lock
from app.services.settings import get_app_settings

router = APIRouter(prefix="/ranking")


@router.get("/score-current/estimate", response_model=ScoreCurrentEstimateResponse)
def score_current_estimate(
    opening_id: int | None = None,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> ScoreCurrentEstimateResponse:
    opening_id = resolve_visible_opening_id(db, opening_id)
    require_ai_actions_available(db, opening_id)
    settings = get_app_settings(db)
    report, result = current_scoring_estimate(db, opening_id, settings)
    estimated_usd = float(result["estimated_usd"])
    return ScoreCurrentEstimateResponse(
        eligible=int(result["total"]),
        to_analyze=int(result["to_analyze"]),
        cached=int(result["cached"]),
        dimensions=len(report.dimensions),
        estimated_usd=estimated_usd,
        cap_usd=settings.ai.spending_cap_usd,
        within_cap=estimated_usd <= settings.ai.spending_cap_usd,
    )


@router.post("/score-current")
def score_current(
    opening_id: int | None = None,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
    provider: AIProvider = Depends(get_ai_provider),
) -> StreamingResponse:
    """Fill missing scores without changing the current dimensions or tier layout."""
    opening_id = resolve_visible_opening_id(db, opening_id)
    require_ai_actions_available(db, opening_id)
    settings = get_app_settings(db)
    report, estimate = current_scoring_estimate(db, opening_id, settings)
    if estimate["to_analyze"] == 0:
        raise Problem(
            "unchanged_pool",
            detail="Every eligible applicant is already scored against the current criteria.",
        )
    try:
        enforce_cap(estimate, settings.ai.spending_cap_usd)
    except SpendingCapExceeded as exc:
        raise Problem(
            "cap_exceeded",
            detail=str(exc),
            cap_usd=settings.ai.spending_cap_usd,
            estimated_usd=estimate["estimated_usd"],
        ) from exc

    lease = acquire_run_lock(db, user_id=user.id, kind=SCORE_CURRENT_KIND)
    if lease is None:
        raise Problem(
            "run_in_progress",
            detail="Another screening or ranking run is in progress. Try again in about 10 minutes.",
        )

    def stream() -> Iterator[str]:
        try:
            pool = applications_to_score(db, opening_id)
            inputs_fingerprint = rank_inputs_fingerprint(db, opening_id, settings, applications=pool)
            candidates = applications_needing_scores(
                db, pool, report, settings.ai.dimension_scoring_model,
            )
            yield emit(PhaseEvent(phase=SCORES, total=len(candidates)))
            tally = ScoreTally()
            started = time.perf_counter()
            for processed, result in enumerate(
                score_dimensions(
                    db,
                    provider,
                    applications=candidates,
                    report=report,
                    settings=settings,
                    max_workers=settings.ai.max_workers,
                ),
                start=1,
            ):
                tally.add(result)
                yield emit(
                    ProgressEvent(
                        phase=SCORES,
                        processed=processed,
                        total=len(candidates),
                    )
                )
            if tally.failed == 0:
                analysis = get_current_analysis(db, opening_id)
                if analysis is not None:
                    record_rank_inputs(db, analysis, inputs_fingerprint)
            record_run_cost(
                db,
                kind=SCORE_CURRENT_KIND,
                passes={
                    "Dimension scoring": tally.as_pass_cost(
                        settings.ai.dimension_scoring_model
                    )
                },
                durations_ms={
                    "Dimension scoring": round((time.perf_counter() - started) * 1000)
                },
                estimated_usd=estimate["estimated_usd"],
                triggered_by_user_id=user.id,
                opening_id=opening_id,
            )
            yield emit(
                RankSummary(
                    dimensions=len(report.dimensions),
                    scored=tally.processed,
                    failed=tally.failed,
                    total_cost_usd=round(tally.cost_usd, 4),
                )
            )
        finally:
            release_run_lock(db, lease)

    return StreamingResponse(stream(), media_type="application/x-ndjson")
