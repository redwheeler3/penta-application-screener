"""Cost estimation for the dimension-scoring pass.

Kept separate from ``dimension_scoring`` (the pass itself) because the estimate models a
*different* thing: the projected $ of a scoring call before it runs, with its own token
constants and history-vs-cache-aware fallback ladder. The pass module owns the prompt, the
cache, and the run loop; this module reads those (``build_prompt``, ``PROMPT_VERSION``, the
cache-grid query) to price the work. The dependency is one-way — the pass never imports this.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.ai.analysis import CostEstimate, observed_avg_tokens
from app.ai.dimension_scoring import (
    KIND_PREFIX,
    PROMPT_VERSION,
    applications_to_score,
    build_prompt,
    missing_dimensions_by_application,
)
from app.ai.pricing import cost_usd
from app.ai.provider import Usage
from app.ai.schemas import PoolDimensionReport
from app.db.models import Application
from app.schemas.settings import AppSettings, effective_reasoning_effort
from app.services.cost_report import recent_pass_fresh_usd
from app.services.ranking.analysis import get_current_analysis
from app.services.ranking.dimensions import current_dimension_report

# Per-DIMENSION output tokens — used to price the estimate. Output is genuinely
# per-dimension (each dimension emits its own score + rationale + evidence), so the
# split rows learn it honestly; this fallback is for the first run only.
SCORING_FALLBACK_OUTPUT_TOKENS = 160

# Per-CANDIDATE input tokens when no real prompt is available to measure (the
# pre-discovery first-Rank estimate). One scoring call sends the candidate's full
# facts + essays ONCE regardless of how many dimensions it scores, so input is a
# per-call constant, not per-dimension — see estimate_dimension_scoring.
SCORING_FALLBACK_INPUT_TOKENS_PER_CANDIDATE = 2900

# Dimensions assumed per candidate before any discovery, so the first-Rank estimate has a
# count to multiply by. Only used for the first Rank; later runs use observed dimensions.
# The upper end of the observed 30–35 range avoids surprising users with an underestimate.
ASSUMED_DIMENSIONS_FIRST_RUN = 35

# Token approximation for a built prompt when we have one but no tokenizer: ~4 chars
# per token (matches observed ~2,980 chars/4 vs. ~2,880 real input on this pool).
_CHARS_PER_TOKEN = 4


# The scoring estimate is the shared cost-estimate shape (see analysis.CostEstimate);
# scoring builds it via its own cache-aware fallback ladder rather than the shared engine.
ScoringEstimate = CostEstimate


def _avg_output_tokens_per_dimension(db: Session, model_id: str) -> int:
    """Average OUTPUT tokens of one stored per-dimension scoring row, learned across
    every dimension set (the ``dimension_scoring:`` prefix), or the fallback.

    Only output is learned this way: output is genuinely per-dimension (each emits
    its own score + rationale + evidence), so the split rows measure it honestly.
    Input is NOT — see ``estimate_dimension_scoring`` for why.
    """
    observed = observed_avg_tokens(
        db, kind=KIND_PREFIX, model_id=model_id, prompt_version=PROMPT_VERSION,
        kind_prefix=f"{KIND_PREFIX}:",
    )
    return observed[1] if observed is not None else SCORING_FALLBACK_OUTPUT_TOKENS


def _per_candidate_input_tokens(db: Session, report: PoolDimensionReport | None) -> int:
    """Input tokens for one candidate's scoring call. Input is a per-CALL constant —
    the candidate's full facts + essays are sent once regardless of how many
    dimensions the call scores — so we measure it from a real built prompt (~chars/4)
    rather than from the stored per-dimension rows, whose input was split by however
    many dimensions each historical call happened to score (a single-dimension
    carry-forward call would otherwise attribute the whole ~2.9k-token prompt to one
    row and poison the average). Falls back to a constant before discovery exists.
    """
    if report is None:
        return SCORING_FALLBACK_INPUT_TOKENS_PER_CANDIDATE
    candidates = applications_to_score(db)
    if not candidates:
        return SCORING_FALLBACK_INPUT_TOKENS_PER_CANDIDATE
    sample = candidates[0]
    prompt = build_prompt(sample, report.dimensions)
    return len(prompt) // _CHARS_PER_TOKEN


def estimate_dimension_scoring(
    db: Session,
    settings: AppSettings,
    *,
    prefer_history: bool = True,
    include_coverage: bool = True,
    candidates: list[Application] | None = None,
) -> ScoringEstimate:
    """Pre-run scoring estimate that respects the per-dimension cache.

    Input cost is per candidate; output cost is per dimension. Estimate in priority order:
    recent measured scoring spend, current uncached candidate/dimension pairs, then a
    first-run ceiling when no dimension report exists.

    The measured path reflects stable-pool reruns accurately but cannot see a newly changed
    cache until another run reaches the ledger. Callers that need exact current coverage use
    ``include_coverage`` and the cache-aware path.
    """
    model_id = settings.ai.dimension_scoring_model
    reasoning_effort = effective_reasoning_effort(
        model_id, settings.ai.dimension_scoring_reasoning_effort
    )
    # Reuse a pool the caller already computed when given — the union scope is ~15ms and a
    # full-Rank estimate would otherwise recompute it several times per request.
    candidates = candidates if candidates is not None else applications_to_score(db)
    analysis = get_current_analysis(db)
    report = current_dimension_report(analysis) if analysis is not None else None

    # The full-discovery estimate needs only the measured scoring cost, not the
    # current cache counts. Skip N×dimension cache lookups when history already gives
    # that cost; the score-current estimate keeps ``include_coverage`` true because
    # it must name exactly which applicants still need work.
    measured = recent_pass_fresh_usd(db) if prefer_history else None
    if measured is not None and not include_coverage:
        return {
            "total": len(candidates),
            "to_analyze": 0,
            "cached": 0,
            "estimated_usd": round(measured, 4),
        }

    input_tokens = _per_candidate_input_tokens(db, report)
    output_per_dim = _avg_output_tokens_per_dimension(db, model_id)

    def _call_cost(uncached_dims: int) -> float:
        # One call: shared input once + output per uncached dimension.
        return cost_usd(
            model_id,
            Usage(input_tokens=input_tokens, output_tokens=output_per_dim * uncached_dims),
        )

    if report is None:
        # First run: no dimensions discovered yet and nothing cached → the original
        # ceiling (every candidate scores every assumed dimension).
        per_candidate = _call_cost(ASSUMED_DIMENSIONS_FIRST_RUN)
        return {
            "total": len(candidates),
            "to_analyze": len(candidates),
            "cached": 0,
            "estimated_usd": round(per_candidate * len(candidates), 4),
        }

    # Count the real uncached work per candidate against the current dims (also drives
    # the honest cached/to_analyze counts the UI shows). A fully-cached candidate makes
    # no call, matching run-time behavior.
    missing_by_application = missing_dimensions_by_application(
        db, candidates, report, model_id, reasoning_effort
    )
    count_based = 0.0
    fully_cached = 0
    for application in candidates:
        to_score = missing_by_application[application.id]
        if not to_score:
            fully_cached += 1
            continue
        count_based += _call_cost(len(to_score))

    # A full Rank has discovery-dependent scoring work, so its estimate favours recent
    # measured runs. Scoring an existing dimension set has no such uncertainty: use the
    # exact current cache count instead.
    estimated = measured if measured is not None else count_based

    return {
        "total": len(candidates),
        "to_analyze": len(candidates) - fully_cached,
        "cached": fully_cached,
        "estimated_usd": round(estimated, 4),
    }
