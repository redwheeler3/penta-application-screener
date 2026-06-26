"""Quality-flag analysis: the informational AI integrity pass over eligible
applications (SPEC "AI Quality Flags").

Flags are never disqualifying — they surface things a human screener should be aware
of. Builds the per-application prompt and runs it via the shared engine.
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
    derive_prompt_version,
    estimate_cost,
    screen_applications,
)
from app.ai.prompt_fragments import PROTECTED_CHARACTERISTICS_NOTE
from app.ai.provider import AIProvider
from app.ai.schemas import QualityFlagReport
from app.db.models import Application, ApplicationStatus, StatusSource
from app.domain.status import apply_machine_status
from app.schemas.settings import AppSettings
from app.services.application_import import extract_essays

KIND = "quality_flags"

SYSTEM_PROMPT = f"""\
You are a careful assistant helping a housing co-op screening committee review applications for data-integrity concerns.
You only surface things a human should be aware of; you never make eligibility or acceptance decisions.
Be conservative: only flag something when there is concrete evidence in the application.
When in doubt, do not flag.
{PROTECTED_CHARACTERISTICS_NOTE}"""

# The static instruction template. Held as a module constant (with a {pet_policy}
# placeholder for the only per-settings value) so the cache version can be derived
# from the prompt text — see PROMPT_VERSION. The pet policy is interpolated per call
# in build_prompt; it is deliberately NOT part of the version (a policy change does
# not alter how the model reasons, only the threshold it cites).
_INSTRUCTIONS_TEMPLATE = """\
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
- Pet descriptions that violate the co-op pet policy ({pet_policy}). The pets field is free text, so account for negation ('no pets') and unclear phrasing.

Do NOT flag (these are normal and must be ignored):
- A child or co-applicant having a different surname from the applicant. Blended families and differing surnames are common and are NOT suspicious.
- Missing optional information, or an answer simply being short.
- Anything related to protected characteristics, family structure, national origin, or the cultural origin of a name.

Cite only short excerpts or field names as evidence; do not quote whole essays back.

Before returning the structured flags, briefly explain your reasoning as Markdown. Then return the structured flags."""

# Derived from the static prompt text: any edit to the template or system prompt
# (including a shared fragment they embed) changes this, re-running exactly this
# pass's cache. No manual bumping. See derive_prompt_version.
PROMPT_VERSION = derive_prompt_version(SYSTEM_PROMPT, _INSTRUCTIONS_TEMPLATE)


def _pet_policy_line(settings: AppSettings) -> str:
    parts = [f"at most {settings.max_dogs} dog(s)", f"at most {settings.max_cats} cat(s)"]
    if not settings.allow_other_pets:
        parts.append("no other/exotic pets")
    return "; ".join(parts)


def build_prompt(application: Application, settings: AppSettings) -> str:
    """Assemble the analysis input from normalized fields, essays, and pets. Essays
    are included in full (they're the basis for several flags), but the model is
    told not to echo them back wholesale.
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

    # Fill the only per-settings value into the static template. The field/essay
    # JSON is appended separately (its braces would collide with .format()).
    instructions = _INSTRUCTIONS_TEMPLATE.format(pet_policy=_pet_policy_line(settings))

    fields_json = json.dumps(fields, indent=2, default=str)
    essays_json = json.dumps(essays, indent=2, default=str)
    return f"{instructions}\n\nFIELDS:\n{fields_json}\n\nESSAYS:\n{essays_json}"


def applications_to_analyze(db: Session) -> list[Application]:
    """The applications the quality-flag pass should (re-)analyze: everything except
    those the rules disqualified.

    Covers any eligible application plus those a *previous AI pass* marked
    ineligible — re-analyzing the latter lets a prompt change clear a flag and
    restore eligibility, not just the reverse (``apply_machine_status`` handles both
    and keeps human statuses sticky). Rules-ineligible apps are excluded (rules
    outrank AI, so re-running could never change their status). Human-owned statuses
    are included so their flags refresh for the staleness nudge.
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
        prompt_version=PROMPT_VERSION,
        # Fallback only (no real usage yet). Order-of-magnitude from observed runs;
        # the prompt asks for a Markdown narrative, so output is several hundred tokens.
        fallback_input_tokens=2800,
        fallback_output_tokens=550,
    )


def _apply_outcome_status(
    db: Session, application: Application, outcome: AnalysisOutcome
) -> None:
    """Set the application's status from an outcome's flags and commit.

    The AI actor sets status unless a human owns the decision (flags still refresh
    for the staleness nudge). Touches the session, so it runs on the ``db`` thread.
    """
    report: QualityFlagReport = outcome.output
    apply_machine_status(
        application,
        has_reasons=bool(application.hard_filter_reasons),
        has_ai_flags=bool(report.flags),
    )
    db.commit()


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
        prompt_version=PROMPT_VERSION,
        prompt=build_prompt(application, settings),
        system_prompt=SYSTEM_PROMPT,
    )
    _apply_outcome_status(db, application, outcome)
    return outcome


def screen_quality_flags(
    db: Session,
    provider: AIProvider,
    *,
    applications: list[Application],
    settings: AppSettings,
    max_workers: int,
) -> Iterator[ScreeningResult]:
    """Run the quality-flag pass over ``applications`` via the shared screening
    engine, applying status from each result's flags as it completes.
    """
    return screen_applications(
        db,
        provider,
        applications=applications,
        kind=KIND,
        schema=QualityFlagReport,
        model_id=settings.ai.first_pass_model,
        prompt_version=PROMPT_VERSION,
        build_prompt=lambda application: build_prompt(application, settings),
        system_prompt=SYSTEM_PROMPT,
        max_workers=max_workers,
        on_result=lambda application, outcome: _apply_outcome_status(
            db, application, outcome
        ),
    )
