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
    DimensionScoringPlan,
    build_prompt,
    missing_dimensions_by_application,
)
from app.ai.pricing import cost_usd
from app.ai.provider import Usage
from app.ai.schemas import PoolDimensionReport
from app.db.models import Application
from app.schemas.settings import AppSettings, effective_reasoning_effort
from app.services.cost_report import project_pass_cost_from_history
from app.services.ranking.analysis import get_current_analysis
from app.services.ranking.dimensions import current_dimension_report

# Per-DIMENSION output tokens — used to price the estimate. Output is genuinely
# per-dimension (each dimension emits its own score + rationale + evidence), so the
# split rows learn it honestly; this fallback is for the first run only.
SCORING_FALLBACK_OUTPUT_TOKENS = 160

# Per-CANDIDATE input tokens when no real prompt is available to measure (the
# pre-discovery first-Rank estimate). One scoring call sends the candidate's full
# facts + essays ONCE regardless of how many dimensions it scores, so input is a
# per-call constant, not per-dimension — see estimate_rank_scoring.
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


def estimate_scoring_plan(db: Session, plan: DimensionScoringPlan) -> ScoringEstimate:
    """Price exactly the misses and captured prompt sizes that execution will consume."""
    output_per_dim = _avg_output_tokens_per_dimension(db, plan.model_id)
    estimated = sum(cost_usd(plan.model_id, Usage(
        input_tokens=app.prompt_length // _CHARS_PER_TOKEN,
        output_tokens=output_per_dim * len(app.dimensions_to_score),
    )) for app in plan.applicants if app.dimensions_to_score)
    return {"total": len(plan.applicants), "to_analyze": plan.to_analyze,
        "cached": len(plan.applicants) - plan.to_analyze, "estimated_usd": round(estimated, 4)}


def _avg_output_tokens_per_dimension(db: Session, model_id: str) -> int:
    """Average OUTPUT tokens of one stored per-dimension scoring row, learned across
    every dimension set (the ``dimension_scoring:`` prefix), or the fallback.

    Only output is learned this way: output is genuinely per-dimension (each emits
    its own score + rationale + evidence), so the split rows measure it honestly.
    Input is NOT — see ``estimate_rank_scoring`` for why.
    """
    observed = observed_avg_tokens(
        db, kind=KIND_PREFIX, model_id=model_id, prompt_version=PROMPT_VERSION,
        kind_prefix=f"{KIND_PREFIX}:",
    )
    return observed[1] if observed is not None else SCORING_FALLBACK_OUTPUT_TOKENS


def _per_candidate_input_tokens(
    candidates: list[Application], report: PoolDimensionReport | None
) -> int:
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
    if not candidates:
        return SCORING_FALLBACK_INPUT_TOKENS_PER_CANDIDATE
    sample = candidates[0]
    prompt = build_prompt(sample, report.dimensions)
    return len(prompt) // _CHARS_PER_TOKEN


def estimate_rank_scoring(
    db: Session, opening_id: int, settings: AppSettings, *, candidates: list[Application],
) -> float:
    """Project full-Rank scoring spend for the supplied pool.

    Prefer recent measured spend. Without history, price current cache misses or
    the first-run dimension ceiling. Exact score-current work uses a captured plan.
    """
    if not candidates:
        return 0.0
    measured = project_pass_cost_from_history(db, opening_id, model_id=settings.ai.dimension_scoring_model)
    if measured is not None:
        return round(measured, 4)

    model_id = settings.ai.dimension_scoring_model
    reasoning_effort = effective_reasoning_effort(
        model_id, settings.ai.dimension_scoring_reasoning_effort
    )
    analysis = get_current_analysis(db, opening_id)
    report = current_dimension_report(analysis) if analysis is not None else None
    input_tokens = _per_candidate_input_tokens(candidates, report)
    output_per_dim = _avg_output_tokens_per_dimension(db, model_id)

    def call_cost(dimensions: int) -> float:
        return cost_usd(model_id, Usage(
            input_tokens=input_tokens, output_tokens=output_per_dim * dimensions,
        ))

    if report is None:
        return round(call_cost(ASSUMED_DIMENSIONS_FIRST_RUN) * len(candidates), 4)

    missing = missing_dimensions_by_application(
        db, candidates, report, model_id, reasoning_effort
    )
    return round(sum(call_cost(len(dimensions)) for dimensions in missing.values()
        if dimensions), 4)
