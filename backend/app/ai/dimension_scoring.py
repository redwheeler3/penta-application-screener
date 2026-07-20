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
    PassResult,
    cache_key,
    cached_outcome,
    derive_prompt_version,
    exception_type_name,
    log,
    run_in_pool,
    store_result,
)
from app.ai.applicant_facts import applicant_facts
from app.ai.prompt_fragments import (
    ENGLISH_POLISH_NOTE,
    INJECTION_GUARD_NOTE,
)
from app.ai.provider import AIProvider, AIResult, Usage
from app.ai.schemas import (
    DimensionScore,
    DimensionScoringReport,
    PoolDimension,
    PoolDimensionReport,
    ScoreConfidence,
)
from app.db.models import Application, ApplicationAIResult, ApplicationStatus
from app.schemas.settings import AppSettings
from app.services.application_import import extract_essays

KIND_PREFIX = "dimension_scoring"

SYSTEM_PROMPT = f"""\
You are helping a housing co-op screening committee score one applicant against a fixed set of dimensions — this applicant alone, not ranked against others.
Score only on evidence in the applicant's own words; never guess.
Score from -1 (`low_end` pole) to +1 (`high_end` pole), with 0 neutral. An unaddressed dimension scores 0: silence is never negative, even when a `low_end` is worded as absence ("no skills mentioned") — that pole means a DEMONSTRATED low.
Confidence measures how well your evidence pins down the applicant's TRUE standing, not your certainty about their wording. An unaddressed dimension is LOW confidence; reserve HIGH for substantial, direct evidence.
{ENGLISH_POLISH_NOTE}"""


# Static instruction text. No per-call placeholders here: the applicant and
# dimensions are appended as XML data in build_prompt, not formatted into this text.
_INSTRUCTIONS = f"""\
## Task
Score this applicant on EACH of the dimensions in the `<dimensions>` block, returning exactly one entry per dimension. Judge from BOTH the applicant's structured facts and their essays, using whichever the dimension draws on.

## Inputs
The dimensions to score in the `<dimensions>` block, and the applicant's evidence (structured facts and raw essays) in the `<applicant>` block, below.

## Output
For each dimension provide:
- dimension_key: the dimension's key, exactly as given
- score: -1..+1, anchored to the dimension's poles — +1 is `high_end`, -1 is `low_end`, 0 is neutral — judged only on stated evidence; an unaddressed dimension scores 0
- rationale: one neutral sentence from the applicant's facts or words
- evidence: a short quote or field reference; if the dimension is unaddressed, say so plainly rather than leaving it empty
- confidence: low, medium, or high per the rule above; an unaddressed dimension is low confidence.

## Guardrails
- {INJECTION_GUARD_NOTE}
- Score every dimension, even an unaddressed one (0, low confidence, evidence noting it was not addressed).
- Do not invent evidence."""

# Cached pass: version derives from the static prompt text and gates the per-dimension
# cache (see derive_prompt_version). Also folded into the run's rank-inputs
# fingerprint so a prompt edit shows Rank as out of date.
PROMPT_VERSION = derive_prompt_version(SYSTEM_PROMPT, _INSTRUCTIONS)


def build_prompt(
    application: Application,
    dimensions: list[PoolDimension],
) -> str:
    return _build_prompt(_applicant_block(application), dimensions)


def _build_prompt(applicant_block: str, dimensions: list[PoolDimension]) -> str:
    return (
        f"{_INSTRUCTIONS}\n\n<dimensions>\n{_dimensions_block(dimensions)}\n</dimensions>"
        f"\n\n<applicant>\n{applicant_block}\n</applicant>"
    )


def _dimensions_block(dimensions: list[PoolDimension]) -> str:
    """The candidate's uncached dimensions to score, as compact JSON for the prompt.

    Includes ``high_end``/``low_end`` — the concrete meaning of a +1 vs. a -1 score (0 is
    neutral) — so the model anchors each score to the axis's own poles rather than an
    implicit scale.
    """
    dims = [
        {
            "key": d.key,
            "name": d.name,
            "definition": d.definition,
            "high_end": d.high_end,
            "low_end": d.low_end,
        }
        for d in dimensions
    ]
    return json.dumps(dims, indent=2, default=str)


def _applicant_block(application: Application) -> str:
    """The applicant evidence: structured facts plus the raw essays in full.

    Facts must match what discovery saw, or a fact-based dimension is unscoreable.
    Essays are included in full (a single-candidate call is cheap and lets the model
    ground quotes precisely).
    """
    payload: dict[str, object] = {
        "applicant_id": application.id,
        "facts": applicant_facts(application),
        "essays": extract_essays(application.raw_row or {}),
    }
    return json.dumps(payload, indent=2, default=str)


def kind_for_dimension(dimension_key: str) -> str:
    """The cache ``kind`` for one dimension's score, keyed by the dimension key.

    Cross-run reuse rides on the key: ``adopt_matched_keys`` rewrites a matched
    re-discovered dimension to the prior key, so it hits the same cache. Cache
    identity is the key, NOT the definition text (the match pass vouches the concept
    is the same) — editing a definition would need a new key to force a re-score.
    """
    return f"{KIND_PREFIX}:{dimension_key}"


def applications_to_score(db: Session) -> list[Application]:
    """Eligible applications only — same scope as essay analysis."""
    return list(
        db.scalars(
            select(Application)
            .where(Application.status == ApplicationStatus.ELIGIBLE)
            .order_by(Application.id)
        ).all()
    )


def _to_score_dimensions(
    db: Session,
    application: Application,
    report: PoolDimensionReport,
    model_id: str,
) -> tuple[list[PoolDimension], dict[str, DimensionScore], float]:
    """Split a candidate's dimensions into (to-score, cached) by per-key cache hit.
    Returns the dimensions still to score, cached scores keyed by dimension key, and
    the cached rows' original cost for cache-savings accounting.
    """
    to_score: list[PoolDimension] = []
    cached: dict[str, DimensionScore] = {}
    cached_saved_usd = 0.0
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
            cached_saved_usd += outcome.cost_usd
    return to_score, cached, cached_saved_usd


def missing_dimensions_by_application(
    db: Session,
    applications: list[Application],
    report: PoolDimensionReport,
    model_id: str,
) -> dict[int, list[PoolDimension]]:
    """Find cache misses for an applicant × dimension grid in batched queries.

    The confirmation card needs this exact answer. Querying one cache row at a time
    makes its latency grow with every criterion, so fetch the relevant cache keys in
    bounded batches and map the misses back to each applicant.
    """
    keys_by_application = {
        application.id: {
            dimension.key: cache_key(
                application=application,
                kind=kind_for_dimension(dimension.key),
                model_id=model_id,
                prompt_version=PROMPT_VERSION,
            )
            for dimension in report.dimensions
        }
        for application in applications
    }
    all_keys = [
        key
        for by_dimension in keys_by_application.values()
        for key in by_dimension.values()
    ]
    existing: set[str] = set()
    # SQLite's bound-variable ceiling is commonly 999. Keep well below it so the
    # same code handles a much larger applicant pool without a dialect-specific path.
    for start in range(0, len(all_keys), 500):
        existing.update(
            db.scalars(
                select(ApplicationAIResult.cache_key).where(
                    ApplicationAIResult.cache_key.in_(all_keys[start:start + 500])
                )
            )
        )
    return {
        application.id: [
            dimension
            for dimension in report.dimensions
            if keys_by_application[application.id][dimension.key] not in existing
        ]
        for application in applications
    }


def applications_needing_scores(
    db: Session, report: PoolDimensionReport, model_id: str
) -> list[Application]:
    """Eligible applicants with at least one missing score for ``report``."""
    applications = applications_to_score(db)
    missing_by_application = missing_dimensions_by_application(
        db, applications, report, model_id
    )
    return [app for app in applications if missing_by_application[app.id]]


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
    report: PoolDimensionReport,
    cached: dict[str, DimensionScore],
    fresh: dict[str, DimensionScore],
) -> DimensionScoringReport:
    """Merge cached + fresh scores into the candidate's full report, one entry per
    dimension (fresh wins on overlap). A dimension with no score at all (the model
    omitted it despite the retry logic — normally that raises IncompleteScoringError
    before reaching here) gets a NEUTRAL placeholder (0, the signed-scale midpoint): we
    have no evidence, so fabricating a low score would sink the candidate on a model
    glitch (the same silence-is-not-a-weakness rule the prompt applies to an unaddressed
    dimension)."""
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


# A scoring response occasionally omits a dimension we asked for (model non-determinism).
# We re-ask for ONLY the missing ones, up to this many times; if still short, the
# candidate fails loudly rather than persisting a silent partial (a placeholder score
# that reads as "scored 0.0" and hides forever behind a coverage fraction).
MAX_SCORING_RETRIES = 2


class IncompleteScoringError(Exception):
    """The model would not return a score for every requested dimension, even after
    retries — the candidate's scoring failed rather than being silently partial."""


def _score_all_dimensions(
    provider: AIProvider,
    applicant_block: str,
    to_score: list[PoolDimension],
    model_id: str,
) -> AIResult:
    """One candidate's uncached dimensions, scored COMPLETELY — the initial call plus
    targeted re-asks for any dimensions the model omitted, merged into one result whose
    usage sums every call. Raises ``IncompleteScoringError`` if the model still omits a
    dimension after ``MAX_SCORING_RETRIES`` — fail loud, never store a partial.

    No DB work here (runs on a ``run_in_pool`` worker thread); the caller stores the
    returned scores back on the main thread.
    """
    scores: dict[str, DimensionScore] = {}
    input_tokens = output_tokens = 0
    last_model_id = model_id
    remaining = to_score
    for attempt in range(MAX_SCORING_RETRIES + 1):  # 1 initial + N retries
        result = provider.structured_output(
            model_id=model_id,
            schema=DimensionScoringReport,
            prompt=_build_prompt(applicant_block, remaining),
            system_prompt=SYSTEM_PROMPT,
        )
        input_tokens += result.usage.input_tokens
        output_tokens += result.usage.output_tokens
        last_model_id = result.model_id
        returned = {s.dimension_key: s for s in result.output.scores}
        for dim in remaining:
            if dim.key in returned:
                scores[dim.key] = returned[dim.key]
        remaining = [d for d in remaining if d.key not in scores]
        if not remaining:
            break
        if attempt < MAX_SCORING_RETRIES:
            log.warning(
                "Dimension scoring for application %s omitted %d dimension(s); "
                "re-asking (attempt %d): %s",
                "the current applicant", len(remaining), attempt + 1,
                [d.key for d in remaining],
            )
    if remaining:
        raise IncompleteScoringError(
            f"model omitted {len(remaining)} dimension(s) after "
            f"{MAX_SCORING_RETRIES} retries: {[d.key for d in remaining]}"
        )
    return AIResult(
        output=DimensionScoringReport(scores=list(scores.values())),
        usage=Usage(input_tokens=input_tokens, output_tokens=output_tokens),
        model_id=last_model_id,
    )


def score_dimensions(
    db: Session,
    provider: AIProvider,
    *,
    applications: list[Application],
    report: PoolDimensionReport,
    settings: AppSettings,
    max_workers: int,
) -> Iterator[PassResult]:
    """Score every candidate, reusing cached per-dimension scores and batching each
    candidate's uncached dimensions into one model call.

    Mirrors ``screen_applications``' session discipline: all ORM work on this
    thread, only the model call in a worker via ``run_in_pool``.
    """
    model_id = settings.ai.dimension_scoring_model

    # Plan each candidate on the main thread (cache lookups touch the ORM): which
    # dimensions still need scoring, and the cached ones to merge in.
    plans = []
    for application in applications:
        to_score, cached, cached_saved_usd = _to_score_dimensions(
            db, application, report, model_id
        )
        # Workers must never touch an ORM instance: storing an earlier candidate commits
        # on the main thread and expires session objects while slower workers are still
        # building prompts. Snapshot the applicant input before the pool starts.
        applicant_block = _applicant_block(application) if to_score else None
        plans.append((application, applicant_block, to_score, cached, cached_saved_usd))

    def call(plan):
        _application, applicant_block, to_score, _cached, _cached_saved_usd = plan
        if not to_score:
            return None  # fully cached → no model call
        assert applicant_block is not None
        # Score COMPLETELY: initial call + targeted re-asks for any omitted dimension.
        # Raises IncompleteScoringError if the model won't return them all — which
        # run_in_pool surfaces as this candidate's error (fail loud, no partial store).
        return _score_all_dimensions(provider, applicant_block, to_score, model_id)

    for (application, _applicant_block_text, to_score, cached, cached_saved_usd), result, error in run_in_pool(
        plans, call=call, max_workers=max_workers
    ):
        if error is not None:
            error_type = exception_type_name(error)
            log.warning(
                "Dimension scoring failed for application %s: %s",
                application.id, error_type, exc_info=error,
            )
            yield PassResult(
                application=application, outcome=None,
                error=str(error), error_type=error_type,
            )
            continue
        if result is None:  # fully cached
            yield PassResult(
                application=application,
                outcome=AnalysisOutcome(
                    output=_assemble(report, cached, {}), cost_usd=0.0, cached=True
                ),
                fresh_units=0,
                cached_units=len(cached),
                cached_saved_usd=cached_saved_usd,
            )
            continue
        fresh = {s.dimension_key: s for s in result.output.scores}
        share = _split_usage(result.usage, len(to_score))
        call_cost = 0.0
        fresh_count = 0
        for dim in to_score:
            # _score_all_dimensions guarantees every to_score dim is present, so index
            # directly — a KeyError here would mean that contract broke, and failing
            # loud beats silently skipping.
            score = fresh[dim.key]
            outcome = store_result(
                db, application, kind=kind_for_dimension(dim.key), model_id=model_id,
                prompt_version=PROMPT_VERSION,
                result=AIResult(
                    output=score, usage=share, model_id=result.model_id,
                    # No narrative: the scoring prompt requests no reasoning preamble
                    # (structured output only), so this per-decision pass's reasoning IS
                    # the per-dimension rationale + evidence in `score`, surfaced on the
                    # candidate detail page. Persisting the call preamble would duplicate
                    # one near-empty string across every dimension row, read by nothing.
                    narrative=None,
                ),
            )
            call_cost += outcome.cost_usd
            fresh_count += 1
        # The candidate's fresh tokens are the whole call's usage (each stored row got a
        # 1/parts share; summing them back rounds down to ~the call total). Report the
        # call's usage directly so the run ledger's token total stays exact.
        yield PassResult(
            application=application,
            outcome=AnalysisOutcome(
                output=_assemble(report, cached, fresh), cost_usd=call_cost, cached=False,
                input_tokens=result.usage.input_tokens, output_tokens=result.usage.output_tokens,
            ),
            fresh_units=fresh_count,
            cached_units=len(cached),
            cached_saved_usd=cached_saved_usd,
        )
