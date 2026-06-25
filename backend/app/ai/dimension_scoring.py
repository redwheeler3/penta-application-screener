"""Dimension scoring: the per-candidate pass that rates each eligible applicant
against the run's discovered dimensions (SPEC "Pattern Discovery And Dimension
Scoring", milestone 7; per-dimension reuse is the M9 carry-forward Phase 4).

Scores are cached at **per-(candidate, dimension)** granularity: a candidate's
score for a dimension is stored under ``kind = "dimension_scoring:<dimension_key>"``.
Because a re-discovered dimension that the match pass judged identical has its
key rewritten to the prior key (``screening_run.adopt_matched_keys``), it hits
the same cache row and its score is **reused across re-ranks** instead of being
recomputed — only genuinely new or unmatched dimensions are sent to the model.
This is the cost win: a re-rank re-scores the handful of new axes, not the whole
pool against a fresh set.

To stay token-efficient, a candidate's *uncached* dimensions are scored in **one
batched call** (never one call per dimension — the candidate's facts + essays are
never repeated), and the call's tokens are split evenly across the dimensions it
scored when the per-dimension rows are stored. The cached and freshly-scored
dimensions are then merged to assemble the candidate's full score set.

Informational only — like essay analysis it never touches eligibility status, so
there is no ``on_result`` hook. Starts on the first-pass model (Haiku),
measure-first per the SPEC.
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
    observed_avg_tokens,
    run_in_pool,
    store_result,
)
from app.ai.applicant_facts import FILTERED_FACTS_NOTE, applicant_facts
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

SYSTEM_PROMPT = """\
You are helping a housing co-op screening committee score one applicant against a fixed set of dimensions the committee cares about.
Score only on evidence in the applicant's own words; never infer a guess.
Confidence measures how well your evidence pins down the applicant's TRUE standing on a dimension — NOT how sure you are about what they wrote. When an applicant simply did not address a dimension, score it low but with LOW confidence: silence is weak evidence, because they may well have that strength and just not have mentioned it. Being certain they omitted it is not the same as being confident they lack it. Reserve high confidence for dimensions the applicant gave substantial, direct evidence on.
Do not penalize brief, awkward, translated, or non-native English answers for writing polish — judge substance.
Stay neutral and never use protected characteristics. You are scoring this one applicant, not ranking them against others."""


def kind_for_dimension(dimension_key: str) -> str:
    """The cache ``kind`` for one dimension's score, keyed by the dimension key.
    A candidate's score for a key is stored under this kind, so a dimension that
    recurs under the same key reuses the cached score instead of re-scoring.

    Cross-run reuse rides on the key: when the match pass judges a re-discovered
    dimension to be the same concept, ``adopt_matched_keys`` rewrites it to the
    prior key, so it hits the same cache. NB: cache identity is the key, NOT the
    dimension's definition text — the match pass vouches the concept is the same,
    so reuse is sound. (A future "edit a dimension's definition" feature would
    need to change the key to force a re-score.)
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
    """The dimensions the model must score, as compact JSON for the prompt. Only
    the candidate's *uncached* dimensions are passed — the model never re-emits a
    dimension we already have a cached score for."""
    dims = [
        {"key": d.key, "name": d.name, "definition": d.definition}
        for d in dimensions
    ]
    return json.dumps(dims, indent=2, default=str)


def _applicant_block(application: Application, essay_report: dict | None) -> str:
    """The applicant evidence: structured facts, the essay-analysis digest, and
    the raw essays.

    The facts must match what discovery saw (same shared view), or a fact-based
    dimension would be unscoreable here. Essays are included in full (unlike
    discovery, which trims for pool size): a single-candidate call is cheap, and
    the raw essays let the model ground evidence quotes precisely.
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


def build_prompt(
    application: Application,
    dimensions: list[PoolDimension],
    essay_report: dict | None,
) -> str:
    instructions = f"""\
Score this applicant on EACH of the dimensions below, returning exactly one entry per dimension.
Judge from BOTH the applicant's structured facts and their essays, using whichever the dimension draws on.

{FILTERED_FACTS_NOTE}

For each dimension provide:
- dimension_key: the dimension's key, exactly as given
- score: 0..1 for how strongly this applicant exhibits it, judged only on stated evidence
- rationale: one neutral sentence from the applicant's facts or words
- evidence: a short quote or field reference (empty string if there is nothing relevant)
- confidence: low, medium, or high — how well the evidence pins down the applicant's TRUE standing, NOT how sure you are about what they wrote. A dimension the applicant did not address is low confidence even when you are certain it went unmentioned (they may have the strength and simply not have said so).

Score every dimension, even when the applicant did not address it (low score, low confidence). Do not invent evidence."""

    return (
        f"{instructions}\n\nDIMENSIONS:\n{_dimensions_block(dimensions)}"
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


# Fallback PER-DIMENSION token weight, used only on the very first scoring run
# ever (before any real usage exists). After that the estimate self-tunes from
# actual usage across all dimension sets via the ``dimension_scoring:`` prefix.
# Per-dimension now: one stored row is one dimension's split share of a batched
# call, so these are ~(whole-call ÷ dimensions-per-call). Output dominates: each
# dimension emits a score + rationale + evidence.
SCORING_FALLBACK_INPUT_TOKENS = 350
SCORING_FALLBACK_OUTPUT_TOKENS = 130

# Dimensions assumed per candidate when none exist yet (the first Rank, before
# discovery), so the pre-run ceiling estimate has a count to multiply by.
ASSUMED_DIMENSIONS_FIRST_RUN = 15


def _avg_tokens_per_dimension(db: Session, model_id: str) -> tuple[int, int]:
    """Average (input, output) tokens of one stored per-dimension scoring row,
    learned from real usage across every dimension set (the ``dimension_scoring:``
    prefix), or the fallback constants when there is no history yet."""
    return observed_avg_tokens(
        db, kind=KIND_PREFIX, model_id=model_id, kind_prefix=f"{KIND_PREFIX}:"
    ) or (SCORING_FALLBACK_INPUT_TOKENS, SCORING_FALLBACK_OUTPUT_TOKENS)


def estimate_dimension_scoring(
    db: Session, settings: AppSettings
) -> dict[str, object]:
    """Pre-run scoring estimate as a full-pool **ceiling**: price as if every
    eligible candidate scores every dimension.

    The estimate is shown before discovery and the match pass run, so it cannot
    know how many dimensions will carry forward (their scores reused) versus be
    new — and discovery is nondeterministic, so guessing would risk an estimate
    that under-counts and erodes the cap guarantee. We therefore price the
    worst case: the actual run comes in *under* this as carry-forward reuse kicks
    in, and the real saving shows up in the run summary. Dimension count comes
    from the current run (the best available proxy) or a constant on a first run.

    Per-dimension token usage self-tunes across runs (token cost depends on the
    prompt shape, not which axes were discovered), like the other passes.
    """
    model_id = settings.ai.first_pass_model
    candidates = applications_to_score(db)
    run = get_current_run(db)
    report = current_pattern_report(run) if run is not None else None
    dims_per_candidate = len(report.dimensions) if report else ASSUMED_DIMENSIONS_FIRST_RUN

    avg_in, avg_out = _avg_tokens_per_dimension(db, model_id)
    per_dimension = cost_usd(model_id, Usage(input_tokens=avg_in, output_tokens=avg_out))
    pairs = len(candidates) * dims_per_candidate
    return {
        "total": len(candidates),
        "to_analyze": len(candidates),  # ceiling: assume none cached
        "cached": 0,
        "estimated_usd": round(per_dimension * pairs, 4),
    }


# estimate_dimension_scoring is the single scoring estimate now: it always prices
# the whole-pool ceiling, so it serves both the pre-discovery Rank estimate and
# any later "what would scoring cost" question. (The old split into a
# with-dimensions vs. without-dimensions variant is gone: a ceiling needs only a
# dimension *count*, which the current run supplies and a constant covers on a
# first run.)
estimate_scoring_without_dimensions = estimate_dimension_scoring


def _to_score_dimensions(
    db: Session,
    application: Application,
    report: PoolPatternReport,
    model_id: str,
) -> tuple[list[PoolDimension], dict[str, DimensionScore]]:
    """Split a candidate's dimensions into (to-score, cached).

    For each dimension, look up its per-key cache row for this candidate: a hit
    yields a reusable ``DimensionScore`` (the dimension recurs under the same key,
    via ``adopt_matched_keys``); a miss means the model must score it. Returns the
    dimensions still to score and the already-cached scores keyed by dimension
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
        )
        if outcome is None:
            to_score.append(dim)
        else:
            cached[dim.key] = DimensionScore.model_validate(outcome.output.model_dump())
    return to_score, cached


def _split_usage(usage: Usage, parts: int) -> Usage:
    """Divide a batched call's token usage evenly across the dimensions it scored,
    so each per-dimension cache row carries its fair share. Aggregates back to the
    call's real total, keeping cost accounting and the self-tuning estimate honest.
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
    """Merge cached + freshly-scored dimensions into the candidate's full report,
    one entry per discovered dimension (fresh wins on overlap; a dimension the
    model omitted gets a low/empty placeholder so the shape stays complete)."""
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
    """Score every candidate, reusing cached per-dimension scores and batching
    each candidate's uncached dimensions into one model call.

    Mirrors ``screen_applications``' session discipline: all ORM work (cache
    lookups, prompt building, persistence) happens on this thread; only the model
    call runs in a worker, via ``run_in_pool``. Informational — never touches
    status, so there is no ``on_result`` hook.
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
