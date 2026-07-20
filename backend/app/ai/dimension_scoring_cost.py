"""Cost estimation for the dimension-scoring pass.

Kept separate from ``dimension_scoring`` (the pass itself) because the estimate models a
*different* thing: the projected $ of a scoring call before it runs, with its own token
constants and history-vs-cache-aware fallback ladder. The pass module owns the prompt, the
cache, and the run loop; this module reads those (``build_prompt``, ``PROMPT_VERSION``, the
cache-grid query) to price the work. The dependency is one-way — the pass never imports this.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.ai.analysis import observed_avg_tokens
from app.ai.dimension_scoring import (
    KIND_PREFIX,
    PROMPT_VERSION,
    _missing_dimensions_by_application,
    applications_to_score,
    build_prompt,
)
from app.ai.pricing import cost_usd
from app.ai.provider import Usage
from app.ai.schemas import PoolDimensionReport
from app.schemas.settings import AppSettings
from app.services.cost_report import recent_pass_fresh_usd
from app.services.ranking_run import current_dimension_report, get_current_run

# Per-DIMENSION output tokens — used to price the estimate. Output is genuinely
# per-dimension (each dimension emits its own score + rationale + evidence), so the
# split rows learn it honestly; this fallback is for the first run only.
SCORING_FALLBACK_OUTPUT_TOKENS = 160

# Per-CANDIDATE input tokens when no real prompt is available to measure (the
# pre-discovery first-Rank estimate). One scoring call sends the candidate's full
# facts + essays ONCE regardless of how many dimensions it scores, so input is a
# per-call constant, not per-dimension — see estimate_dimension_scoring.
SCORING_FALLBACK_INPUT_TOKENS_PER_CANDIDATE = 2900

# Dimensions assumed per candidate before any discovery, so the first-Rank ceiling
# estimate has a count to multiply by.
ASSUMED_DIMENSIONS_FIRST_RUN = 15

# Token approximation for a built prompt when we have one but no tokenizer: ~4 chars
# per token (matches observed ~2,980 chars/4 vs. ~2,880 real input on this pool).
_CHARS_PER_TOKEN = 4


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
) -> dict[str, object]:
    """Pre-run scoring estimate that respects the per-dimension cache.

    Models the real cost shape of a scoring call: a per-candidate INPUT cost (the
    shared facts + essays, sent once per call — measured from a real prompt) plus a
    per-DIMENSION OUTPUT cost (each dimension's score + rationale + evidence, learned
    from usage). Input is immune to carry-forward skew because it's measured from a
    real built prompt, not the split per-dimension rows.

    History-first, cache-aware. Pricing the whole pool as if nothing were cached would be
    a ~10× over-estimate on a stable-pool re-run (the per-(candidate,dimension) cache
    reuses almost everything) and could wrongly trip the spending cap, so the estimate
    uses two cache-aware signals, in priority order:

    1. **Measured (preferred):** a recency-weighted average of what recent Rank runs
       *actually spent* on fresh scoring (``recent_pass_fresh_usd``). A past run's
       stored scoring ``fresh_usd`` already captures the true re-run shape — reuse plus
       whatever discovery newly minted and scored — so history is the honest predictor,
       no invented churn constant. Used whenever any prior Rank recorded a scoring pass.
    2. **Cache-aware count (fallback, no history yet):** count the actually-uncached
       (candidate, dimension) pairs against the current run's dimensions, exactly as
       ``_to_score_dimensions`` does at run time (the same count-the-uncached approach
       the shared ``estimate_cost`` engine uses for per-application passes).
    3. **First-run ceiling (no report at all):** every candidate × assumed dims, nothing
       cached — the genuine worst case before discovery has run once.

    Caveat on the measured path: it reads only the ledger, so it can't see a *current*
    cache change (e.g. a just-synced batch of new applicants that will score fresh) —
    it under-predicts until the next run records the new cost. Fine for the dominant
    locked-pool re-run case; if the pool-changed case proves to underestimate in
    practice, blend in the cache-aware count then (measure-first).
    """
    model_id = settings.ai.dimension_scoring_model
    candidates = applications_to_score(db)
    run = get_current_run(db)
    report = current_dimension_report(run) if run is not None else None

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
    missing_by_application = _missing_dimensions_by_application(
        db, candidates, report, model_id
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
