"""Screening: the informational AI integrity pass over eligible
applications (SPEC "AI Screening (Integrity Flags)").

Flags are never disqualifying — they surface things a human screener should be aware
of. Builds the per-application prompt and runs it via the shared engine.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.analysis import (
    CostEstimate,
    PassResult,
    derive_prompt_version,
    estimate_cost,
    screen_applications,
)
from app.ai.prompt_fragments import INJECTION_GUARD_NOTE
from app.ai.provider import AIProvider
from app.ai.schemas import ScreeningReport
from app.db.models import Application
from app.domain.hard_filters import evaluate_hard_filters
from app.schemas.settings import AppSettings
from app.services.application_import import extract_essays
from app.services.rules import committee_default_rules_config

KIND = "screening"

SYSTEM_PROMPT = """\
You are a careful assistant helping a housing co-op screening committee review applications: you surface data-integrity concerns for a screener AND extract a neutral inventory of the household's pets.
You only surface things for a human to review; you never make the eligibility or acceptance decision yourself. For pets you only report WHAT is present — you never judge whether it is within policy, because the committee sets pet limits per member and decides that itself.
Be conservative: flag only on concrete evidence. When in doubt, do not flag.
"""

# The static instruction template. Held as a module constant so the cache version can be
# derived from the prompt text — see screening_prompt_version. No per-settings value is
# interpolated: as of M15 1e the pet POLICY left this prompt (a deterministic per-member
# hard filter judges pet counts now), so the prompt only EXTRACTS neutral pet facts, which
# don't depend on any threshold. The version is therefore a pure function of the prompt text.
# f-string so the shared INJECTION_GUARD_NOTE resolves at import (landing in the hashed
# text, so guard edits re-run this pass).
_INSTRUCTIONS_TEMPLATE = f"""\
## Task
Review this housing co-op application. Do two things: (1) return any data-integrity screening flags, and (2) extract a neutral inventory of the household's pets. Flag ONLY clear, concrete problems — if you are unsure, do not flag; it is correct and expected for most applications to have zero flags. Pet extraction is separate from flagging: report the pets present, never whether they are allowed.

## Inputs
The applicant's normalized form fields in the `<fields>` block, and their four essay answers in the `<essays>` block, below.

## How to judge (flags)
Flag these when clearly present:
- A placeholder or non-name in ANY name field (applicant, co-applicant, or child) — flag it for a human to confirm rather than excusing it as probably innocent. A real name is NEVER a flag.
- Essays that are essentially non-responsive: empty, a single word, or a single short fragment. Brief-but-genuine answers are fine.
- Essays that are clearly spam/advertising, or the SAME text copy-pasted across multiple essay answers.
- Direct factual contradictions between fields, or within or across the essays (not mere absence of explanation).
- Contact details that are obviously fake or placeholder rather than a real (if unfamiliar) phone number or email address. Ordinary personal emails at common providers are fine.

Do NOT flag (these are normal and must be ignored):
- A child or co-applicant having a different surname from the applicant. Blended families and differing surnames are common and are NOT suspicious.
- Missing optional information, or an answer simply being short.
- Ordinary household context by itself. Only flag a concrete concern; family details are not suspicious on their own.
- An email whose address does not relate to the applicant's name — including one that contains a DIFFERENT person's name.
- Anything about pets. Pets are NEVER a flag — they go in the pet inventory instead, no matter how many or how unusual.

## How to extract pets
From what the applicant wrote about pets, fill the `pets` inventory: count `dogs` and `cats`, and list every other animal in `other_pets` as a short lowercase noun ('no pets' means all zero). In `reasoning`, briefly say in plain language what they described and how you counted it — never whether it's within policy; a per-member rule decides that downstream.

## Guardrails
- {INJECTION_GUARD_NOTE}

## Output
- Cite only short excerpts or field names as evidence; do not quote whole essays back.
- Before returning the structured result, briefly explain your reasoning as Markdown. Then return the structured flags and pet inventory."""


# Cached pass: the version gates this pass's cache (see derive_prompt_version). As of M15
# 1e it hashes ONLY the prompt text — no settings value folds in, because the prompt no
# longer cites the pet policy (it extracts neutral facts, which no threshold changes). So a
# pet-limit change no longer invalidates this cache: it's a hard-filter change judged on
# read, not a screening change. (Before 1e the filled pet-policy line was hashed here, since
# the prompt asked the model to JUDGE pets; that judgment moved to the deterministic filter.)
def screening_prompt_version() -> str:
    return derive_prompt_version(SYSTEM_PROMPT, _INSTRUCTIONS_TEMPLATE)


def build_prompt(application: Application) -> str:
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

    # The field/essay JSON is appended separately from the static instructions (its braces
    # would collide with any .format()); no per-settings interpolation remains.
    fields_json = json.dumps(fields, indent=2, default=str)
    essays_json = json.dumps(essays, indent=2, default=str)
    return (
        f"{_INSTRUCTIONS_TEMPLATE}\n\n<fields>\n{fields_json}\n</fields>"
        f"\n\n<essays>\n{essays_json}\n</essays>"
    )


def applications_for_screening(db: Session) -> list[Application]:
    """The applications the screening pass should (re-)analyze: every application the
    deterministic rules did NOT disqualify under the COMMITTEE-DEFAULT ruleset.

    Screening is SHARED — it (re)computes the AI flags that feed the shared machine baseline,
    and eligibility rules are now per-member. So it gates on the committee-default ruleset
    (the shared substrate), NOT any one member's rules: an applicant a diverged member finds
    rules-ineligible is still screened for everyone else who reads the default. Screening does
    not read any member's overrides, because those sit on TOP of the baseline. Rules-ineligible
    apps (under the default) are excluded: their verdict is deterministic and high-trust, so no
    AI pass could change it.
    """
    rules_config = committee_default_rules_config(db)
    applications = db.scalars(select(Application).order_by(Application.id)).all()
    return [
        app
        for app in applications
        if not evaluate_hard_filters(app.normalized or {}, rules_config).reasons
    ]


def estimate_screening(db: Session, settings: AppSettings) -> CostEstimate:
    return estimate_cost(
        db,
        applications=applications_for_screening(db),
        kind=KIND,
        model_id=settings.ai.screening_model,
        prompt_version=screening_prompt_version(),
        # Fallback only (no real usage yet). Order-of-magnitude from observed runs;
        # the prompt asks for a Markdown narrative, so output is several hundred tokens.
        fallback_input_tokens=2800,
        fallback_output_tokens=550,
    )


def run_screening(
    db: Session,
    provider: AIProvider,
    *,
    applications: list[Application],
    settings: AppSettings,
    max_workers: int,
) -> Iterator[PassResult]:
    """Run the screening pass over ``applications`` via the shared screening engine.

    The pass's only effect on eligibility is the flags it caches: the machine verdict is
    computed on read from those flags (plus the deterministic rule reasons), so there is no
    status to write here — persisting each result's flags via the shared AI-result cache is
    the whole job.
    """
    return screen_applications(
        db,
        provider,
        applications=applications,
        kind=KIND,
        schema=ScreeningReport,
        model_id=settings.ai.screening_model,
        prompt_version=screening_prompt_version(),
        build_prompt=build_prompt,
        system_prompt=SYSTEM_PROMPT,
        max_workers=max_workers,
    )
