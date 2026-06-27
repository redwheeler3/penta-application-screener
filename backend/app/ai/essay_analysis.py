"""Essay analysis: per-candidate extraction of what applicants said in their four
essays, normalized into a fixed schema (SPEC "Essay Analysis").

Purely informational — it never touches eligibility status. It extracts what was
said for the committee and the ranker; evaluation is the ranker's job. Runs through
the shared cached engine with ``kind="essay_analysis"``.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.analysis import (
    AnalysisOutcome,
    PassResult,
    analyze_application,
    derive_prompt_version,
    estimate_cost,
    screen_applications,
)
from app.ai.prompt_fragments import (
    ENGLISH_POLISH_NOTE,
    INJECTION_GUARD_NOTE,
    PROTECTED_CHARACTERISTICS_NOTE,
)
from app.ai.provider import AIProvider
from app.ai.schemas import EssayAnalysisReport
from app.db.models import Application, ApplicationStatus
from app.schemas.settings import AppSettings
from app.services.application_import import extract_essays

KIND = "essay_analysis"

SYSTEM_PROMPT = f"""\
You are a careful assistant helping a housing co-op screening committee read applicant essays.
Your job is to extract and neutrally summarize WHAT each applicant said — not to judge how good it is.
You never decide eligibility, fit, or whether someone should be interviewed; a later step does the judging.
Extract only what is supported by the essays; never invent or infer beyond the text.
{PROTECTED_CHARACTERISTICS_NOTE}
{ENGLISH_POLISH_NOTE}"""

# Static instruction text. No per-call placeholders: the essays are appended as XML
# data in build_prompt, not formatted into this text.
_INSTRUCTIONS = f"""\
## Task
Read this applicant's co-op membership essays and extract what they said into the structured fields. This is neutral extraction, NOT evaluation — describe what they conveyed; do not rate fit, commitment, or quality, and do not speculate.

## Inputs
The applicant's four co-op membership essay answers, in the `<essays>` block below.

## Output
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

## Guardrails
- {INJECTION_GUARD_NOTE}
- Content bleeds across the four questions (skills appear in the introduction, etc.) — pull each fact into the right field wherever it appears.
- Leave a field null or empty if the applicant did not address it; do not fill gaps with guesses.
- Return the structured analysis directly."""

# Cached pass: version derives from the static prompt text and gates this pass's
# cache (see derive_prompt_version). Also folded into the run's rank-inputs
# fingerprint so a prompt edit shows Rank as out of date.
PROMPT_VERSION = derive_prompt_version(SYSTEM_PROMPT, _INSTRUCTIONS)


def build_prompt(application: Application) -> str:
    """Assemble the essay-analysis input from the candidate's four essays. Only the
    essays are sent; structured form fields stay available to the ranker elsewhere.
    """
    essays = extract_essays(application.raw_row or {})
    essays_json = json.dumps(essays, indent=2, default=str)
    return f"{_INSTRUCTIONS}\n\n<essays>\n{essays_json}\n</essays>"


def applications_to_analyze(db: Session) -> list[Application]:
    """The applications the essay-analysis pass should analyze: eligible only.
    No value in summarizing essays for disqualified applicants — the committee ranks
    the eligible pool. (Screening flags use a broader scope; they can change status.)
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
        prompt_version=PROMPT_VERSION,
        # Fallback only (no real usage yet). Essays make this heavier on input than
        # screening flags; the estimate self-tunes once a run has happened.
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
        prompt_version=PROMPT_VERSION,
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
) -> Iterator[PassResult]:
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
        prompt_version=PROMPT_VERSION,
        build_prompt=build_prompt,
        system_prompt=SYSTEM_PROMPT,
        max_workers=max_workers,
    )
