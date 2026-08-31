"""HTTP boundary for estimating and starting a full Rank run."""

from collections.abc import Iterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.ai.analysis import (
    SpendingCapExceeded,
    enforce_cap,
)
from app.ai.dimension_discovery import (
    eligible_applications,
)
from app.ai.provider import AIProvider
from app.api.dependencies import get_ai_provider, require_current_user
from app.core.problems import Problem
from app.db.models import User
from app.db.session import get_db
from app.schemas.ranking import (
    RankEstimateBreakdown,
    RankEstimateResponse,
)
from app.schemas.settings import AppSettings
from app.services.application_scope import resolve_visible_opening_id
from app.services.opening_selection import require_ai_actions_available
from app.services.ranking.analysis import (
    get_current_analysis,
    ranking_is_current,
)
from app.services.ranking.estimates import build_rank_estimate
from app.services.ranking.pipeline import stream_rank
from app.services.run_lock import acquire_run_lock, release_run_lock
from app.services.settings import get_app_settings

router = APIRouter(prefix="/ranking")

@router.get("/run/estimate", response_model=RankEstimateResponse)
def rank_estimate(
    opening_id: int | None = None,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
) -> RankEstimateResponse:
    opening_id = resolve_visible_opening_id(db, opening_id)
    require_ai_actions_available(db, opening_id)
    settings: AppSettings = get_app_settings(db)
    # Compute the union pool ONCE and thread it through the estimate — the guard, the rank
    # estimate, and the scoring estimate all range over the same ~15ms union, so deriving it
    # once here (instead of each recomputing) is most of the confirm-card latency saved.
    pool = eligible_applications(db, opening_id)
    if not pool:
        raise Problem("no_eligible_applications", detail="No eligible applications to rank.")
    result = build_rank_estimate(db, opening_id, settings, pool=pool)
    cap = settings.ai.spending_cap_usd
    breakdown = result["breakdown"]
    return RankEstimateResponse(
        eligible=result["eligible"],
        fan_out=result["fan_out"],
        breakdown=RankEstimateBreakdown(
            criteria_usd=breakdown["criteria_usd"],
            match_usd=breakdown["match_usd"],
            scoring_usd=breakdown["scoring_usd"],
        ),
        estimated_usd=result["estimated_usd"],
        approximate=result["approximate"],
        cap_usd=cap,
        within_cap=result["estimated_usd"] <= cap,
        # When the pool is unchanged, the ranking is already current; the UI uses
        # this to say "up to date" instead of offering to spend.
        ranking_current=ranking_is_current(
            db, get_current_analysis(db, opening_id), settings, applications=pool
        ),
    )


@router.post("/run")
def rank_run(
    opening_id: int | None = None,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
    provider: AIProvider = Depends(get_ai_provider),
) -> StreamingResponse:
    """Run the full ranking chain — find criteria → score → consolidate — streaming NDJSON.
    The combined cost is checked against the cap once before any model call, so an over-cap
    run fails fast with a 402 and spends nothing.

    Stream shape: a ``phase`` line per pass, ``progress`` lines for the
    per-candidate passes, then a final ``summary`` with the combined cost.
    Discovery is one call, so it emits a phase line and its result, no progress.
    """
    opening_id = resolve_visible_opening_id(db, opening_id)
    require_ai_actions_available(db, opening_id)
    settings: AppSettings = get_app_settings(db)
    if not eligible_applications(db, opening_id):
        raise Problem("no_eligible_applications", detail="No eligible applications to rank.")

    # An unchanged pool needs no re-rank, but one is allowed: discovery is nondeterministic,
    # so re-running deliberately gives the committee a fresh set of criteria. The
    # confirmation card is the gate (it flags that nothing requires a re-run); a member who
    # confirms here has opted in on purpose.
    estimate = build_rank_estimate(db, opening_id, settings)
    try:
        enforce_cap(estimate, settings.ai.spending_cap_usd)
    except SpendingCapExceeded as exc:
        raise Problem(
            "cap_exceeded",
            detail=str(exc),
            cap_usd=settings.ai.spending_cap_usd,
            estimated_usd=float(estimate["estimated_usd"]),
        ) from exc

    # Serialize against other in-flight runs. The full Rank is the run whose overlap
    # is genuinely destructive — two concurrent Ranks each create an Analysis and
    # last-writer-wins strands the loser's MemberRanking — so this guard is what closes that
    # hazard. Released in the stream's finally (covers the early return + any pass raising).
    if not acquire_run_lock(db, user_id=user.id, kind="rank"):
        raise Problem(
            "run_in_progress",
            detail="Another screening or ranking run is in progress. Try again in about 10 minutes.",
        )

    def stream() -> Iterator[str]:
        try:
            yield from stream_rank(
                db,
                provider,
                settings,
                user,
                opening_id=opening_id,
                estimated_usd=float(estimate["estimated_usd"]),
            )
        finally:
            release_run_lock(db, user_id=user.id)
    return StreamingResponse(stream(), media_type="application/x-ndjson")
