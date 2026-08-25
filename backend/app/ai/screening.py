"""Screening: the informational AI integrity pass over eligible
applications (SPEC "AI Screening (Integrity Flags)").

Flags are never disqualifying — they surface things a human screener should be aware
of. Builds the per-application prompt and runs it via the shared engine.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

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
from app.schemas.settings import AppSettings, effective_reasoning_effort
from app.services.application_content import extract_essays
from app.services.application_scope import committee_applications
from app.services.eligibility import rules_eligible_application_ids

KIND = "screening"

SYSTEM_PROMPT = """\
You are a careful assistant helping a housing co-op screening committee review applications: you surface data-integrity concerns for a screener AND extract a neutral inventory of the household's pets.
You only surface things for a human to review; you never make the eligibility or acceptance decision yourself. For pets you only report WHAT is present — you never judge whether it is within policy, because the committee sets pet limits per member and decides that itself.
Be conservative: flag only on concrete evidence. When in doubt, do not flag.
"""

# The static instruction template. Held as a module constant so the cache version can be
# derived from the prompt text. The prompt extracts neutral pet facts; deterministic
# per-member rules apply the policy, so no settings value belongs in this version.
# f-string so the shared INJECTION_GUARD_NOTE resolves at import (landing in the hashed
# text, so guard edits re-run this pass).
_INSTRUCTIONS_TEMPLATE = f"""\
## Task
Review this housing co-op application. Do two things: (1) return any data-integrity screening flags, and (2) extract a neutral inventory of the household's pets. Flag ONLY clear, concrete problems — if you are not totally sure, do not flag; it is correct and expected for most applications to have zero flags. Pet extraction is separate from flagging: report the pets present, never whether they are allowed.

## Inputs
The applicant's normalized form fields in the `<fields>` block, and their four essay answers in the `<essays>` block, below.

## How to judge (flags)
Flag these when clearly present:
- A placeholder or non-name in ANY name field (applicant, co-applicant, or child). A real name is NEVER a flag.
- Essay answers with no substantive content at all: a totally empty essay or an essay composed entirely of a single short fragment. A relevant statement is substantive even if brief.
- Essays that are clearly spam/advertising, the SAME text copy-pasted across multiple essay answers, or that does not answer the question posed.
- Direct factual contradictions between fields (excluding names and email fields), within or across the essays, or between fields and essays.
- A placeholder or keyboard-mash field (e.g. 'asdf@asdf.asdf', 'test@test.test', '111-111-1111', 'TBD'). Judge ONLY the characters of the value itself — is it gibberish, repeated, or a placeholder. A normal-looking email or phone is real no matter whose name it contains or resembles.

Do NOT flag (these are normal and must be ignored):
- A child or co-applicant having a different surname from the applicant, including a plausible spelling variation, typo, or letter transposition. These are common and are NOT suspicious.
- An essay self-introducing with a different real name(s) than the name field(s) (e.g. "My name is Michael" when the form says "Kwang su Yun"). We do not want to discriminate on people from different countries, so never flag this even if you can't figure out the relationship between the real name(s) and the anglisized ones.
- Missing optional information, or an answer simply being short.
- NEVER flag an incomplete or cut-off essay, no matter how abrupt. Ignore the unfinished tail; any relevant completed statement is substantive, and the committee can see the cutoff itself.
- Ordinary household context by itself. Only flag a concrete concern; family details are not suspicious on their own.
- An email or phone that doesn't MATCH A NAME — the applicant's own, the co-applicant's, or an unrelated person's. A name mismatch is common and harmless (we can still reach the applicant), so NEVER flag it, no matter how egregious the mismatch. Please reduce noise here — we truly never follow up on this. (This is only about names not matching. A gibberish/placeholder value is still junk — flag that, per the rule above.)
- Anything about pets. Pets are NEVER a flag — they go in the pet inventory instead, no matter how many or how unusual.

## How to extract pets
From what the applicant wrote about pets, fill the `pets` inventory: count dogs and cats, and list every other animal in `other_pets` as a short lowercase noun ('no pets' means all zero). Record each animal AS NAMED, even if it seems fictional or implausible — never drop one because it isn't a "real" animal. In `reasoning`, briefly say in plain language what they described and how you counted it.

## Guardrails
- {INJECTION_GUARD_NOTE}

## Output
- Cite only short excerpts or field names as evidence; do not quote whole essays back.
- Before returning the structured result, briefly explain your reasoning as Markdown. Then return the structured flags and pet inventory."""


# Cached pass: the version hashes only the prompt text because the prompt extracts neutral
# facts rather than applying configurable policy. Pet-limit changes therefore do not
# invalidate the screening cache.
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
    """The applications the screening pass should (re-)analyze: every application that is
    RULES-eligible for AT LEAST ONE member (the union of all members' rulesets).

    Screening is SHARED — it (re)computes the AI flags + pet facts that feed the machine
    baseline once for everyone. Its scope is the rules-only union (``rules_eligible_
    application_ids``), NOT the committee default alone: an applicant a diverged member finds
    rules-eligible must still be screened, or that member would see them eligible with no AI
    result. This matches Rank, which already scopes on the union. Rules-only (no flags/pet
    facts) because those don't exist pre-screen — screening is what produces them. Rules-
    ineligible-for-everyone apps are excluded: their verdict is deterministic, so no AI pass
    could change it. (Member overrides sit on TOP of the baseline and aren't read here.)
    """
    scope = rules_eligible_application_ids(db)
    return [
        app
        for app in committee_applications(db)
        if app.id in scope
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
        reasoning_effort=effective_reasoning_effort(
            settings.ai.screening_model, settings.ai.screening_reasoning_effort
        ),
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
        reasoning_effort=effective_reasoning_effort(
            settings.ai.screening_model, settings.ai.screening_reasoning_effort
        ),
    )
