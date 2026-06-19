"""Quality-flag analysis: the informational AI integrity pass over eligible
applications (SPEC "AI Quality Flags").

Flags are never disqualifying — they surface things a human screener should be
aware of. This module builds the per-application prompt and runs the cached,
cost-capped analysis via the shared engine in ``analysis.py``.
"""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.analysis import AnalysisOutcome, analyze_application, estimate_cost
from app.ai.provider import AIProvider
from app.ai.schemas import QualityFlagReport
from app.db.models import Application, ApplicationStatus, StatusSource
from app.domain.status import apply_machine_status
from app.schemas.settings import AppSettings
from app.services.application_import import extract_essays

KIND = "quality_flags"

SYSTEM_PROMPT = """\
You are a careful assistant helping a housing co-op screening committee review applications for data-integrity concerns. 
You only surface things a human should be aware of; you never make eligibility or acceptance decisions. 
Be conservative: only flag something when there is concrete evidence in the application. 
When in doubt, do not flag. 
Use a neutral, factual tone and never speculate about protected characteristics."""


def _pet_policy_line(settings: AppSettings) -> str:
    parts = [f"at most {settings.max_dogs} dog(s)", f"at most {settings.max_cats} cat(s)"]
    if not settings.allow_other_pets:
        parts.append("no other/exotic pets")
    return "; ".join(parts)


def build_prompt(application: Application, settings: AppSettings) -> str:
    """Assemble the analysis input from normalized fields, essays, and pets.

    Essays are included in full because they are the basis for several flags
    (minimal/spam/AI-generated/duplicated), but the model is instructed not to
    echo them back wholesale.
    """
    normalized = application.normalized or {}
    essays = extract_essays(application.raw_row or {})

    fields = {
        "applicant_name": normalized.get("applicant_name"),
        "co_applicant_name": normalized.get("co_applicant_name"),
        "child_details": normalized.get("child_details"),
        "pets_text": normalized.get("pets_text"),
        "applicant_email": normalized.get("applicant_email"),
        "co_applicant_email": normalized.get("co_applicant_email"),
        "co_applicant_phone": normalized.get("co_applicant_phone"),
    }

    # Static instructions as one editable block; only the pet-policy line is
    # interpolated. The field/essay JSON is appended separately because its braces
    # would collide with f-string interpolation.
    instructions = f"""\
Review this housing co-op application for data-integrity concerns and return any quality flags. 
Flag ONLY clear, concrete problems. 
If you are unsure, do not flag. 
It is correct and expected for most applications to have zero flags.

Flag these when clearly present:
- Names that are obviously placeholders or fake (e.g. 'Baby', 'TBD', 'Test', 'asdf', 'N/A'). A real-looking name is NEVER a flag.
- Essays that are essentially non-responsive: empty, 'n/a', a single word, or a single short fragment. Brief-but-genuine answers are fine.
- Essays that are clearly spam/advertising, or the SAME text copy-pasted across multiple essay answers.
- Direct factual contradictions between fields (not mere absence of explanation).
- Contact details that are clearly fake or placeholder: phone numbers with all identical or sequential digits (e.g. '000-000-0000', '111-111-1111'), and email addresses that are obvious placeholders or keyboard mashing (e.g. 'asdf@asdf.asdf', 'test@test.test', 'qwerty@...'). Ordinary personal emails at common providers are fine.
- Pet descriptions that violate the co-op pet policy ({_pet_policy_line(settings)}). The pets field is free text, so account for negation ('no pets') and unclear phrasing.

Do NOT flag (these are normal and must be ignored):
- A child or co-applicant having a different surname from the applicant. Blended families and differing surnames are common and are NOT suspicious.
- Missing optional information, or an answer simply being short.
- Anything related to protected characteristics, family structure, national origin, or the cultural origin of a name.

Cite only short excerpts or field names as evidence; do not quote whole essays back.

Before returning the structured flags, briefly explain your reasoning as Markdown. Then return the structured flags."""

    fields_json = json.dumps(fields, indent=2, default=str)
    essays_json = json.dumps(essays, indent=2, default=str)
    return f"{instructions}\n\nFIELDS:\n{fields_json}\n\nESSAYS:\n{essays_json}"


def applications_to_analyze(db: Session) -> list[Application]:
    """The applications the quality-flag pass should (re-)analyze.

    Covers everything except those the deterministic rules disqualified: any
    currently-eligible application, plus those a *previous AI pass* marked
    ineligible. Re-analyzing AI-flagged applications lets a prompt change revise
    the verdict in either direction — an app it once flagged can be cleared and
    restored to eligible, not just the reverse. ``apply_machine_status`` already
    handles both transitions and leaves human-set statuses sticky.

    Rules-ineligible applications are excluded: rules outrank AI in
    ``resolve_machine_status``, so re-running AI on them could never change their
    status and would only waste spend. Human-owned statuses are included so their
    flags refresh for the staleness nudge, without their status being overwritten.
    """
    return list(
        db.scalars(
            select(Application)
            .where(
                (Application.status == ApplicationStatus.ELIGIBLE)
                | (
                    (Application.status == ApplicationStatus.INELIGIBLE)
                    & (Application.status_source != StatusSource.RULES)
                )
            )
            .order_by(Application.id)
        ).all()
    )


def estimate_quality_flags(db: Session, settings: AppSettings) -> dict[str, object]:
    return estimate_cost(
        db,
        applications=applications_to_analyze(db),
        kind=KIND,
        model_id=settings.ai.first_pass_model,
        # Fallback only — used when there is no real usage to learn from yet.
        # Order-of-magnitude figures from observed runs (prompt asks for a full
        # Markdown narrative, so output is several hundred tokens, not tens).
        fallback_input_tokens=2800,
        fallback_output_tokens=550,
    )


def analyze_one(
    db: Session,
    provider: AIProvider,
    *,
    application: Application,
    settings: AppSettings,
) -> AnalysisOutcome:
    outcome = analyze_application(
        db,
        provider,
        application=application,
        kind=KIND,
        schema=QualityFlagReport,
        model_id=settings.ai.first_pass_model,
        prompt=build_prompt(application, settings),
        system_prompt=SYSTEM_PROMPT,
    )

    # The AI actor sets status from its findings unless a human owns the
    # decision (then the flags are still refreshed for the staleness nudge).
    report: QualityFlagReport = outcome.output
    apply_machine_status(
        application,
        has_reasons=bool(application.hard_filter_reasons),
        has_ai_flags=bool(report.flags),
    )
    db.commit()
    return outcome
