"""Fill missing scores for the current criteria without creating a new analysis."""

import time
from collections.abc import Generator

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.ai.analysis import SpendingCapExceeded, enforce_cap, exception_type_name
from app.ai.dimension_scoring import (
    applications_to_score,
    plan_dimension_scoring,
    score_planned_dimensions,
)
from app.ai.dimension_scoring_cost import estimate_scoring_plan
from app.ai.pricing import MeasuredProvider
from app.ai.provider import AIProvider
from app.api.dependencies import get_ai_provider, require_current_user
from app.core.problems import Problem
from app.core.work_cancellation import WorkCancelled
from app.db.models import User
from app.db.session import get_db
from app.schemas.events import ErrorEvent, PhaseEvent, ProgressEvent, RankSummary, emit
from app.schemas.ranking import ScoreCurrentEstimateResponse
from app.services.applications.scope import resolve_visible_opening_id
from app.services.cost_report import (
    SCORE_CURRENT_KIND,
    RunCostRecorder,
    record_run_cost,
)
from app.services.openings.selection import require_ai_actions_available
from app.services.ranking.analysis import get_current_analysis, record_rank_inputs
from app.services.ranking.dimensions import current_dimension_report
from app.services.ranking.freshness import rank_inputs_fingerprint
from app.services.ranking.pipeline import SCORES, ScoreTally
from app.services.run_lock import RunLeaseLost, acquire_run_lock, release_run_lock
from app.services.run_stream import RunStreamingResponse
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
    analysis = get_current_analysis(db, opening_id)
    report = current_dimension_report(analysis) if analysis is not None else None
    if report is None:
        raise Problem("run_required", detail="Discover ranking criteria before scoring applicants against them.")
    plan = plan_dimension_scoring(db, applications=applications_to_score(db, opening_id), report=report, settings=settings)
    result = estimate_scoring_plan(db, plan)
    estimated_usd = float(result["estimated_usd"])
    return ScoreCurrentEstimateResponse(
        eligible=int(result["total"]),
        to_analyze=int(result["to_analyze"]),
        cached=int(result["cached"]),
        cached_to_refresh=len(plan.refresh_application_ids),
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
) -> RunStreamingResponse:
    """Fill missing scores without changing the current dimensions or tier layout."""
    opening_id = resolve_visible_opening_id(db, opening_id)
    lease = acquire_run_lock(db, user_id=user.id, kind=SCORE_CURRENT_KIND)
    if lease is None:
        raise Problem("run_in_progress", detail="Another screening or ranking run is in progress. Try again in about 10 minutes.")
    try:
        require_ai_actions_available(db, opening_id)
        settings = get_app_settings(db)
        analysis = get_current_analysis(db, opening_id)
        report = current_dimension_report(analysis) if analysis is not None else None
        if report is None:
            raise Problem("run_required", detail="Discover ranking criteria before scoring applicants against them.")
        pool = applications_to_score(db, opening_id)
        inputs_fingerprint = rank_inputs_fingerprint(db, opening_id, settings, applications=pool)
        plan = plan_dimension_scoring(db, applications=pool, report=report, settings=settings)
        estimate = estimate_scoring_plan(db, plan)
        if plan.to_analyze == 0 and not plan.refresh_application_ids:
            raise Problem("unchanged_pool", detail="Every eligible applicant already uses the current scores.")
        try:
            enforce_cap(estimate, settings.ai.spending_cap_usd)
        except SpendingCapExceeded as exc:
            raise Problem("cap_exceeded", detail=str(exc), cap_usd=settings.ai.spending_cap_usd,
                estimated_usd=estimate["estimated_usd"]) from exc
    except BaseException:
        release_run_lock(db, lease)
        raise

    def stream() -> Generator[str]:
        yield emit(PhaseEvent(phase=SCORES, total=plan.to_analyze))
        tally = ScoreTally()
        started = time.perf_counter()
        processed = 0
        scored = 0
        measured = MeasuredProvider(provider, label="Dimension scoring")
        try:
            for result in score_planned_dimensions(db, measured, plan=plan, max_workers=settings.ai.max_workers):
                tally.add(result)
                if not result.failed and result.fresh_units == 0:
                    continue
                processed += 1
                if not result.failed:
                    scored += 1
                yield emit(
                    ProgressEvent(
                        phase=SCORES,
                        processed=processed,
                        total=plan.to_analyze,
                    )
                )
            if tally.failed == 0:
                record_rank_inputs(db, analysis, inputs_fingerprint)
        except (WorkCancelled, RunLeaseLost):
            raise
        except Exception as error:
            db.rollback()
            record_run_cost(db, kind=SCORE_CURRENT_KIND, status="failed", failed_pass="Dimension scoring",
                failure_type=exception_type_name(error)[:120],
                passes={"Dimension scoring": measured.failed_pass_cost(tally.as_pass_cost(settings.ai.dimension_scoring_model))},
                durations_ms={"Dimension scoring": round((time.perf_counter() - started) * 1000)},
                estimated_usd=estimate["estimated_usd"], triggered_by_user_id=user.id, opening_id=opening_id)
            yield emit(ErrorEvent(phase=SCORES, message="Scoring stopped early. Saved results remain available."))
            return
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
                scored=scored,
                failed=tally.failed,
                total_cost_usd=round(tally.cost_usd, 4),
            )
        )

    return RunStreamingResponse(db, lease, stream(), phase=SCORES,
        cost=RunCostRecorder(SCORE_CURRENT_KIND, estimate["estimated_usd"], user.id, opening_id))
