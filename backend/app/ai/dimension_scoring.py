"""Dimension scoring: the per-candidate pass that rates each eligible applicant
against the run's discovered dimensions (SPEC "Pattern Discovery And Dimension
Scoring", milestone 7).

This is per-application, so it runs through the shared cached, cost-capped
``screen_applications`` engine like quality flags and essay analysis. Two things
make it specific to a run:

- The prompt embeds the run's discovered dimensions (from pattern discovery), so
  scores are only meaningful relative to that dimension set.
- Because the shared cache key does not see the prompt body, the dimension set
  is folded into the ``kind`` as ``dimension_scoring:<dims_hash>``. Distinct
  dimension sets therefore get distinct cache entries instead of colliding on
  stale scores.

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
    analyze_application,
    estimate_cost,
    screen_applications,
)
from app.ai.applicant_facts import FILTERED_FACTS_NOTE, applicant_facts
from app.ai.essay_analysis import KIND as ESSAY_ANALYSIS_KIND
from app.ai.provider import AIProvider
from app.ai.schemas import DimensionScoringReport, EssayAnalysisReport, PoolPatternReport
from app.db.models import Application, ApplicationAIResult, ApplicationStatus
from app.schemas.settings import AppSettings
from app.services.application_import import extract_essays
from app.services.screening_run import dimensions_hash

KIND_PREFIX = "dimension_scoring"

SYSTEM_PROMPT = """\
You are helping a housing co-op screening committee score one applicant against a fixed set of dimensions the committee cares about.
Score only on evidence in the applicant's own words; absence of evidence is a low score with low confidence, never an inferred guess.
Do not penalize brief, awkward, translated, or non-native English answers for writing polish — judge substance.
Stay neutral and never use protected characteristics. You are scoring this one applicant, not ranking them against others."""


def kind_for(report: PoolPatternReport) -> str:
    """The cache ``kind`` for scoring against this report's dimension set.

    Folds the dimensions hash into the kind so two runs with different
    dimensions never share cached scores (see SPEC: the shared cache key does not
    include the prompt body).
    """
    return f"{KIND_PREFIX}:{dimensions_hash(report)}"


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


def _dimensions_block(report: PoolPatternReport) -> str:
    """The dimensions the model must score, as compact JSON for the prompt."""
    dims = [
        {"key": d.key, "name": d.name, "definition": d.definition}
        for d in report.dimensions
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
    application: Application, report: PoolPatternReport, essay_report: dict | None
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
- confidence: low, medium, or high — how well the available evidence supports your score

Score every dimension, even when the applicant did not address it (low score, low confidence). Do not invent evidence."""

    return (
        f"{instructions}\n\nDIMENSIONS:\n{_dimensions_block(report)}"
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


def estimate_dimension_scoring(
    db: Session, report: PoolPatternReport, settings: AppSettings
) -> dict[str, object]:
    return estimate_cost(
        db,
        applications=applications_to_score(db),
        kind=kind_for(report),
        model_id=settings.ai.first_pass_model,
        # Fallback only — used before any real usage exists for this dimension
        # set. Scoring sends essays plus the dimension list and returns a few
        # structured entries, so it is in the same range as essay analysis.
        fallback_input_tokens=3200,
        fallback_output_tokens=700,
    )


def analyze_one(
    db: Session,
    provider: AIProvider,
    *,
    application: Application,
    report: PoolPatternReport,
    settings: AppSettings,
) -> AnalysisOutcome:
    essay_report = _essay_reports(db, [application.id]).get(application.id)
    return analyze_application(
        db,
        provider,
        application=application,
        kind=kind_for(report),
        schema=DimensionScoringReport,
        model_id=settings.ai.first_pass_model,
        prompt=build_prompt(application, report, essay_report),
        system_prompt=SYSTEM_PROMPT,
    )


def screen_dimension_scores(
    db: Session,
    provider: AIProvider,
    *,
    applications: list[Application],
    report: PoolPatternReport,
    settings: AppSettings,
    max_workers: int,
) -> Iterator[ScreeningResult]:
    """Run the scoring pass over ``applications`` via the shared engine. No
    ``on_result`` hook: scoring is informational and never changes status.
    """
    essay_reports = _essay_reports(db, [app.id for app in applications])
    return screen_applications(
        db,
        provider,
        applications=applications,
        kind=kind_for(report),
        schema=DimensionScoringReport,
        model_id=settings.ai.first_pass_model,
        build_prompt=lambda application: build_prompt(
            application, report, essay_reports.get(application.id)
        ),
        system_prompt=SYSTEM_PROMPT,
        max_workers=max_workers,
    )
