"""Essay analysis: per-candidate extraction of what applicants said in their
four essays, normalized into a fixed schema (SPEC "Essay Analysis (Milestone 6)").

This pass is purely informational. Unlike the quality-flag pass, it never touches
an application's eligibility status — it extracts facts for the committee to read
and for the milestone 7 ranker to consume. Evaluation against discovered criteria
is the ranker's job, so this pass extracts what was said and does not judge it.

The work runs through the shared cached, cost-capped engine in ``analysis.py``
with ``kind="essay_analysis"``.
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
from app.ai.provider import AIProvider
from app.ai.schemas import EssayAnalysisReport
from app.db.models import Application, ApplicationStatus
from app.schemas.settings import AppSettings
from app.services.application_import import extract_essays

KIND = "essay_analysis"

SYSTEM_PROMPT = """\
You are a careful assistant helping a housing co-op screening committee read applicant essays.
Your job is to extract and neutrally summarize WHAT each applicant said — not to judge how good it is.
You never decide eligibility, fit, or whether someone should be interviewed; a later step does the judging.
Extract only what is supported by the essays; never invent or infer beyond the text, and never speculate about protected characteristics.
Do not penalize brief, awkward, translated, or non-native English answers — capture their substance regardless of writing polish."""


def build_prompt(application: Application) -> str:
    """Assemble the essay-analysis input from the candidate's four essays.

    Only the essays are sent — this pass is about essay content, not the
    structured form fields (those stay available to the ranker from the source).
    """
    essays = extract_essays(application.raw_row or {})

    instructions = """\
Read this applicant's co-op membership essays and extract what they said into the structured fields.
This is neutral extraction, NOT evaluation — describe what they conveyed; do not rate fit, commitment, or quality, and do not speculate.

Fill each field from the essays:
- summary: a 2-4 sentence neutral digest across all four answers.
- household_context: who is in the household, as introduced. Null if not stated.
- employment_background: the applicant's (and co-applicant's) work situation as narrated. Null if not stated.
- interests: interests they mentioned.
- values: values they expressed.
- skills_offered: concrete skills they (or the co-applicant) offered to help run or maintain the co-op.
- prior_co_op_experience: any previous co-op experience stated. Null if none given.
- stated_motivations: reasons they gave for wanting to live in a co-op.
- stated_contributions: ways they said they would be a valuable member.
- evidence: short direct quotes or phrases grounding the above. Do not quote whole essays.

Content bleeds across the four questions (skills appear in the introduction, etc.) — pull each fact into the right field wherever it appears. Leave a field null or empty if the applicant did not address it; do not fill gaps with guesses.

Before returning the structured analysis, briefly explain your extraction as Markdown. Then return the structured analysis."""

    essays_json = json.dumps(essays, indent=2, default=str)
    return f"{instructions}\n\nESSAYS:\n{essays_json}"


def applications_to_analyze(db: Session) -> list[Application]:
    """The applications the essay-analysis pass should analyze: eligible only.

    There is no value in summarizing essays for rules- or AI-disqualified
    applicants — the committee ranks the eligible pool. (Quality flags use a
    broader scope because they can *change* status; essay analysis cannot.)
    """
    return list(
        db.scalars(
            select(Application)
            .where(Application.status == ApplicationStatus.ELIGIBLE)
            .order_by(Application.id)
        ).all()
    )


def estimate_essay_analysis(db: Session, settings: AppSettings) -> dict[str, object]:
    return estimate_cost(
        db,
        applications=applications_to_analyze(db),
        kind=KIND,
        model_id=settings.ai.first_pass_model,
        # Fallback only — used when there is no real usage to learn from yet.
        # Essays make this pass heavier on input than quality flags; the estimate
        # self-tunes from real usage once a run has happened.
        fallback_input_tokens=3200,
        fallback_output_tokens=600,
    )


def analyze_one(
    db: Session,
    provider: AIProvider,
    *,
    application: Application,
    settings: AppSettings,
) -> AnalysisOutcome:
    """Analyze one application's essays. Informational only — no status change."""
    return analyze_application(
        db,
        provider,
        application=application,
        kind=KIND,
        schema=EssayAnalysisReport,
        model_id=settings.ai.first_pass_model,
        prompt=build_prompt(application),
        system_prompt=SYSTEM_PROMPT,
    )


def screen_essays(
    db: Session,
    provider: AIProvider,
    *,
    applications: list[Application],
    settings: AppSettings,
    max_workers: int,
) -> Iterator[ScreeningResult]:
    """Run the essay-analysis pass over ``applications`` via the shared screening
    engine. No ``on_result`` hook: this pass never changes eligibility status.
    """
    return screen_applications(
        db,
        provider,
        applications=applications,
        kind=KIND,
        schema=EssayAnalysisReport,
        model_id=settings.ai.first_pass_model,
        build_prompt=build_prompt,
        system_prompt=SYSTEM_PROMPT,
        max_workers=max_workers,
    )
