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
from app.db.models import Application, ApplicationStatus
from app.domain.status import apply_machine_status
from app.schemas.settings import AppSettings
from app.services.application_import import extract_essays

KIND = "quality_flags"

SYSTEM_PROMPT = (
    "You are a careful assistant helping a housing co-op screening committee "
    "review applications for data-integrity concerns. You only surface things a "
    "human should be aware of; you never make eligibility or acceptance "
    "decisions. Be conservative: only flag something when there is concrete "
    "evidence in the application. When in doubt, do not flag. Use a neutral, "
    "factual tone and never speculate about protected characteristics."
)


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

    return (
        "Review this housing co-op application for data-integrity concerns and "
        "return any quality flags. Flag ONLY clear, concrete problems. If you "
        "are unsure, do not flag. It is correct and expected for most "
        "applications to have zero flags.\n\n"
        "Flag these when clearly present:\n"
        "- Names that are obviously placeholders or fake (e.g. 'Baby', 'TBD', "
        "'Test', 'asdf', 'N/A'). A real-looking name is NEVER a flag.\n"
        "- Essays that are essentially non-responsive: empty, 'n/a', a single "
        "word, or a single short fragment. Brief-but-genuine answers are fine.\n"
        "- Essays that are clearly spam/advertising, or the SAME text "
        "copy-pasted across multiple essay answers.\n"
        "- Direct factual contradictions between fields (not mere absence of "
        "explanation).\n"
        "- Contact details that are clearly fake or placeholder: phone numbers "
        "with all identical or sequential digits (e.g. '000-000-0000', "
        "'111-111-1111'), and email addresses that are obvious placeholders or "
        "keyboard mashing (e.g. 'asdf@asdf.asdf', 'test@test.test', "
        "'qwerty@...'). Ordinary personal emails at common providers are fine.\n"
        "- Pet descriptions that violate the co-op pet policy "
        f"({_pet_policy_line(settings)}). The pets field is free text, so "
        "account for negation ('no pets') and unclear phrasing.\n\n"
        "Do NOT flag (these are normal and must be ignored):\n"
        "- A child or co-applicant having a different surname from the "
        "applicant. Blended families and differing surnames are common and "
        "are NOT suspicious.\n"
        "- Missing optional information, or an answer simply being short.\n"
        "- Anything related to protected characteristics, family structure, "
        "national origin, or the cultural origin of a name.\n\n"
        "Cite only short excerpts or field names as evidence; do not quote "
        "whole essays back.\n\n"
        f"FIELDS:\n{json.dumps(fields, indent=2, default=str)}\n\n"
        f"ESSAYS:\n{json.dumps(essays, indent=2, default=str)}"
    )


def eligible_applications(db: Session) -> list[Application]:
    """Quality flags run only over applications that are currently eligible.

    This includes applications a human restored to eligible: AI will refresh
    their flags (and may surface new findings → staleness) without overriding
    the human's status.
    """
    return list(
        db.scalars(
            select(Application)
            .where(Application.status == ApplicationStatus.ELIGIBLE)
            .order_by(Application.id)
        ).all()
    )


def estimate_quality_flags(db: Session, settings: AppSettings) -> dict[str, object]:
    return estimate_cost(
        db,
        applications=eligible_applications(db),
        kind=KIND,
        model_id=settings.ai.first_pass_model,
        # Typical application: short essays. Tuned from live samples.
        avg_input_tokens=900,
        avg_output_tokens=200,
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
