"""Dimension scoring: the per-candidate pass that rates each eligible applicant
against the run's discovered dimensions (SPEC "Pattern Discovery And Dimension
Scoring").

Scores are cached per (candidate, dimension), under
``kind = "dimension_scoring:<dimension_key>"``. A re-discovered dimension the match
pass judged identical has its key rewritten to the prior key
(``adopt_matched_keys``), so it hits the same cache row and its score is reused
across re-ranks — only new or unmatched dimensions are sent to the model.

A candidate's uncached dimensions are scored in one batched call (facts + essays
never repeated), and the call's tokens are split evenly across them when the
per-dimension rows are stored. Cached and fresh scores are then merged.

Informational only — never touches status, so no ``on_result`` hook. Runs on the
first-pass model.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.analysis import (
    AnalysisOutcome,
    ScreeningResult,
    cached_outcome,
    derive_prompt_version,
    observed_avg_tokens,
    run_in_pool,
    store_result,
)
from app.ai.applicant_facts import FILTERED_FACTS_NOTE, applicant_facts
from app.ai.prompt_fragments import ENGLISH_POLISH_NOTE, PROTECTED_CHARACTERISTICS_NOTE
from app.ai.essay_analysis import KIND as ESSAY_ANALYSIS_KIND
from app.ai.pricing import cost_usd
from app.ai.provider import AIProvider, AIResult, Usage
from app.ai.schemas import (
    DimensionScore,
    DimensionScoringReport,
    EssayAnalysisReport,
    PoolDimension,
    PoolPatternReport,
    ScoreConfidence,
)
from app.db.models import Application, ApplicationAIResult, ApplicationStatus
from app.schemas.settings import AppSettings
from app.services.application_import import extract_essays
from app.services.screening_run import current_pattern_report, get_current_run

KIND_PREFIX = "dimension_scoring"

SYSTEM_PROMPT = f"""\
You are helping a housing co-op screening committee score one applicant against a fixed set of dimensions the committee cares about.
Score only on evidence in the applicant's own words; never infer a guess.
Confidence measures how well your evidence pins down the applicant's TRUE standing on a dimension — NOT how sure you are about what they wrote. When an applicant simply did not address a dimension, score it low but with LOW confidence: silence is weak evidence, because they may well have that strength and just not have mentioned it. Being certain they omitted it is not the same as being confident they lack it. Reserve high confidence for dimensions the applicant gave substantial, direct evidence on.
{ENGLISH_POLISH_NOTE}
{PROTECTED_CHARACTERISTICS_NOTE}
You are scoring this one applicant, not ranking them against others."""


def kind_for_dimension(dimension_key: str) -> str:
    """The cache ``kind`` for one dimension's score, keyed by the dimension key.

    Cross-run reuse rides on the key: ``adopt_matched_keys`` rewrites a matched
    re-discovered dimension to the prior key, so it hits the same cache. Cache
    identity is the key, NOT the definition text (the match pass vouches the concept
    is the same) — editing a definition would need a new key to force a re-score.
    """
    return f"{KIND_PREFIX}:{dimension_key}"


def _essay_reports(db: Session, application_ids: list[int]) -> dict[int, dict]:
    """Most recent essay-analysis output per application, as raw JSON dicts."""
    if not application_ids:
        return {}
    query = (
        select(ApplicationAIResult)
        .where(ApplicationAIResult.kind == ESSAY_ANALYSIS_KIND)
        .where(ApplicationAIResult.application_id.in_(application_ids))
        .order_by(ApplicationAIResult.created_at)
    )
    latest: dict[int, dict] = {}
    for result in db.scalars(query):
        latest[result.application_id] = result.output
    return latest


def _dimensions_block(dimensions: list[PoolDimension]) -> str:
    """The candidate's uncached dimensions to score, as compact JSON for the prompt."""
    dims = [
        {"key": d.key, "name": d.name, "definition": d.definition}
        for d in dimensions
    ]
    return json.dumps(dims, indent=2, default=str)


def _applicant_block(application: Application, essay_report: dict | None) -> str:
    """The applicant evidence: structured facts, the essay-analysis digest, and the
    raw essays.

    Facts must match what discovery saw, or a fact-based dimension is unscoreable.
    Essays are included in full (unlike discovery, which trims for pool size): a
    single-candidate call is cheap and lets the model ground quotes precisely.
    """
    payload: dict[str, object] = {
        "applicant_id": application.id,
        "facts": applicant_facts(application),
    }
    if essay_report is not None:
        payload["essay_analysis"] = EssayAnalysisReport.model_validate(
            essay_report
        ).model_dump(mode="json")
    payload["essays"] = extract_essays(application.raw_row or {})
    return json.dumps(payload, indent=2, default=str)


# Static instruction template; ``{filtered_facts_note}`` is the only fill (a shared
# constant, not per-application data), so the formatted text is identical for every
# applicant. Held as a module constant so the cache version derives from the prompt
# text — and folding the note in via .format keeps it inside the hash, so editing
# FILTERED_FACTS_NOTE re-runs this pass too. See PROMPT_VERSION.
_INSTRUCTIONS_TEMPLATE = """\
Score this applicant on EACH of the dimensions below, returning exactly one entry per dimension.
Judge from BOTH the applicant's structured facts and their essays, using whichever the dimension draws on.

{filtered_facts_note}

For each dimension provide:
- dimension_key: the dimension's key, exactly as given
- score: 0..1 for how strongly this applicant exhibits it, judged only on stated evidence
- rationale: one neutral sentence from the applicant's facts or words
- evidence: a short quote or field reference (empty string if there is nothing relevant)
- confidence: low, medium, or high — how well the evidence pins down the applicant's TRUE standing, NOT how sure you are about what they wrote. A dimension the applicant did not address is low confidence even when you are certain it went unmentioned (they may have the strength and simply not have said so).

Score every dimension, even when the applicant did not address it (low score, low confidence). Do not invent evidence."""

_INSTRUCTIONS = _INSTRUCTIONS_TEMPLATE.format(filtered_facts_note=FILTERED_FACTS_NOTE)

# Derived from the static prompt text (system + instructions, the latter already
# carrying FILTERED_FACTS_NOTE); auto-invalidates this pass's per-dimension cache on
# any edit. See derive_prompt_version.
PROMPT_VERSION = derive_prompt_version(SYSTEM_PROMPT, _INSTRUCTIONS)


def build_prompt(
    application: Application,
    dimensions: list[PoolDimension],
    essay_report: dict | None,
) -> str:
    return (
        f"{_INSTRUCTIONS}\n\nDIMENSIONS:\n{_dimensions_block(dimensions)}"
        f"\n\nAPPLICANT:\n{_applicant_block(application, essay_report)}"
    )


def applications_to_score(db: Session) -> list[Application]:
    """Eligible applications only — same scope as essay analysis."""
    return list(
        db.scalars(
            select(Application)
            .where(Application.status == ApplicationStatus.ELIGIBLE)
            .order_by(Application.id)
        ).all()
    )


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


def _per_candidate_input_tokens(db: Session, report: PoolPatternReport | None) -> int:
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
    essay_report = _essay_reports(db, [sample.id]).get(sample.id)
    prompt = build_prompt(sample, report.dimensions, essay_report)
    return len(prompt) // _CHARS_PER_TOKEN


def estimate_dimension_scoring(
    db: Session, settings: AppSettings
) -> dict[str, object]:
    """Pre-run scoring estimate as a full-pool ceiling: price as if every eligible
    candidate scores every dimension in one call.

    Models the real cost shape of a scoring call: a per-candidate INPUT cost (the
    shared facts + essays, sent once per call — measured from a real prompt) plus a
    per-DIMENSION OUTPUT cost (each dimension's score + rationale + evidence, learned
    from usage) times the dimension count. This is immune to carry-forward skew: a
    past run that scored only one uncached dimension per candidate no longer inflates
    the estimate (the old per-row average treated the whole shared prompt as a single
    dimension's cost). Runs before discovery, so it prices the worst case — every
    candidate scores every dimension; carry-forward reuse brings the actual under it.
    """
    model_id = settings.ai.first_pass_model
    candidates = applications_to_score(db)
    run = get_current_run(db)
    report = current_pattern_report(run) if run is not None else None
    dims_per_candidate = len(report.dimensions) if report else ASSUMED_DIMENSIONS_FIRST_RUN

    input_tokens = _per_candidate_input_tokens(db, report)
    output_tokens = _avg_output_tokens_per_dimension(db, model_id) * dims_per_candidate
    per_candidate = cost_usd(
        model_id, Usage(input_tokens=input_tokens, output_tokens=output_tokens)
    )
    return {
        "total": len(candidates),
        "to_analyze": len(candidates),  # ceiling: assume none cached
        "cached": 0,
        "estimated_usd": round(per_candidate * len(candidates), 4),
    }


# Alias kept for callers; the ceiling estimate serves every scoring-cost question.
estimate_scoring_without_dimensions = estimate_dimension_scoring


def _to_score_dimensions(
    db: Session,
    application: Application,
    report: PoolPatternReport,
    model_id: str,
) -> tuple[list[PoolDimension], dict[str, DimensionScore]]:
    """Split a candidate's dimensions into (to-score, cached) by per-key cache hit.
    Returns the dimensions still to score and the cached scores keyed by dimension
    key, ready to merge.
    """
    to_score: list[PoolDimension] = []
    cached: dict[str, DimensionScore] = {}
    for dim in report.dimensions:
        outcome = cached_outcome(
            db,
            application,
            kind=kind_for_dimension(dim.key),
            schema=DimensionScore,
            model_id=model_id,
            prompt_version=PROMPT_VERSION,
        )
        if outcome is None:
            to_score.append(dim)
        else:
            cached[dim.key] = DimensionScore.model_validate(outcome.output.model_dump())
    return to_score, cached


def _split_usage(usage: Usage, parts: int) -> Usage:
    """Divide a batched call's token usage evenly across the dimensions it scored,
    so each per-dimension cache row carries its fair share (and the rows aggregate
    back to the call's real total).
    """
    parts = max(parts, 1)
    return Usage(
        input_tokens=usage.input_tokens // parts,
        output_tokens=usage.output_tokens // parts,
    )


def _assemble(
    report: PoolPatternReport,
    cached: dict[str, DimensionScore],
    fresh: dict[str, DimensionScore],
) -> DimensionScoringReport:
    """Merge cached + fresh scores into the candidate's full report, one entry per
    dimension (fresh wins on overlap; an omitted dimension gets a low placeholder)."""
    scores: list[DimensionScore] = []
    for dim in report.dimensions:
        score = fresh.get(dim.key) or cached.get(dim.key)
        if score is None:
            score = DimensionScore(
                dimension_key=dim.key, score=0.0, rationale="", evidence="",
                confidence=ScoreConfidence.LOW,
            )
        scores.append(score)
    return DimensionScoringReport(scores=scores)


def score_dimensions(
    db: Session,
    provider: AIProvider,
    *,
    applications: list[Application],
    report: PoolPatternReport,
    settings: AppSettings,
    max_workers: int,
) -> Iterator[ScreeningResult]:
    """Score every candidate, reusing cached per-dimension scores and batching each
    candidate's uncached dimensions into one model call.

    Mirrors ``screen_applications``' session discipline: all ORM work on this
    thread, only the model call in a worker via ``run_in_pool``.
    """
    model_id = settings.ai.first_pass_model
    essay_reports = _essay_reports(db, [app.id for app in applications])

    # Plan each candidate on the main thread (cache lookups touch the ORM): which
    # dimensions still need scoring, and the cached ones to merge in.
    plans = []
    for application in applications:
        to_score, cached = _to_score_dimensions(db, application, report, model_id)
        plans.append((application, to_score, cached))

    def call(plan):
        application, to_score, _cached = plan
        if not to_score:
            return None  # fully cached → no model call
        return provider.structured_output(
            model_id=model_id,
            schema=DimensionScoringReport,
            prompt=build_prompt(application, to_score, essay_reports.get(application.id)),
            system_prompt=SYSTEM_PROMPT,
        )

    for (application, to_score, cached), result, error in run_in_pool(
        plans, call=call, max_workers=max_workers
    ):
        if error is not None:
            yield ScreeningResult(application=application, outcome=None, error=str(error))
            continue
        if result is None:  # fully cached
            yield ScreeningResult(
                application=application,
                outcome=AnalysisOutcome(
                    output=_assemble(report, cached, {}), cost_usd=0.0, cached=True
                ),
            )
            continue
        fresh = {s.dimension_key: s for s in result.output.scores}
        share = _split_usage(result.usage, len(to_score))
        call_cost = 0.0
        for dim in to_score:
            score = fresh.get(dim.key)
            if score is None:
                continue
            outcome = store_result(
                db, application, kind=kind_for_dimension(dim.key), model_id=model_id,
                prompt_version=PROMPT_VERSION,
                result=AIResult(
                    output=score, usage=share, model_id=result.model_id,
                    narrative=result.narrative,
                ),
            )
            call_cost += outcome.cost_usd
        yield ScreeningResult(
            application=application,
            outcome=AnalysisOutcome(
                output=_assemble(report, cached, fresh), cost_usd=call_cost, cached=False
            ),
        )
