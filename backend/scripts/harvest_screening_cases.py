"""Propose SCREENING golden-case candidates from a synthetic analysis's screening cache.

A screening golden case freezes one synthetic applicant, runs it through the real screening
prompt, and grades the produced flag categories per-category (``expected.fires`` must appear,
``expected.absent`` must not). This reconstructs current cache hits for the newest analysis's
opening and emits each as an EXACT slice of the screening input (the same 7 form fields + 4
essays the pass assembles), with the produced flags shown as a labelling hint. Guard-gated by
the analysis's persisted synthetic provenance; PROPOSES only — a human
sets ``expected.fires``/``absent`` + note and drops the HARVEST_ prefix before committing.
See scripts/_harvest_common.py.

    python -m scripts.harvest_screening_cases        # from backend/
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.ai.analysis import cached_outcome
from app.ai.schemas import ScreeningReport
from app.ai.screening import KIND as SCREENING_KIND
from app.ai.screening import screening_prompt_version
from app.db.models import Analysis, Application
from app.schemas.settings import effective_reasoning_effort
from app.services.application_content import extract_essays
from app.services.application_scope import opening_ai_applications
from app.services.settings import get_app_settings
from scripts._harvest_common import opaque_index, open_synthetic_analysis

# The exact fields the screening pass sends (see app/ai/screening.build_prompt) — kept in the
# same order so a harvested `given` is byte-for-byte the input production saw.
_FIELD_KEYS = (
    "applicant_name", "co_applicant_name", "child_details", "pets_text",
    "applicant_email", "co_applicant_email", "co_applicant_phone",
)


@dataclass(frozen=True)
class ScreeningCandidate:
    application: Application
    report: ScreeningReport


def screening_candidates(db: Session, analysis: Analysis) -> list[ScreeningCandidate]:
    """Return current-input screening cache hits from the analysis's opening only."""
    if analysis.opening_id is None:
        return []
    applications = opening_ai_applications(db, analysis.opening_id)
    settings = get_app_settings(db)
    model_id = settings.ai.screening_model
    reasoning_effort = effective_reasoning_effort(
        model_id, settings.ai.screening_reasoning_effort
    )
    candidates: list[ScreeningCandidate] = []
    for application in applications:
        outcome = cached_outcome(
            db,
            application,
            kind=SCREENING_KIND,
            schema=ScreeningReport,
            model_id=model_id,
            prompt_version=screening_prompt_version(),
            reasoning_effort=reasoning_effort,
        )
        if outcome is not None:
            candidates.append(ScreeningCandidate(application, outcome.output))
    return candidates


def _essays_by_column(raw_row: dict) -> dict:
    """Return essays in the same stored shape that ``build_prompt`` reads.

    Built-in answers stay under their canonical ``essays`` object. Retained external
    rows keep their original question keys until retention removes them.
    """
    built_in = raw_row.get("essays")
    if isinstance(built_in, dict):
        return {"essays": built_in}
    return {essay["question"]: essay["answer"] for essay in extract_essays(raw_row)}


def main() -> None:
    db, analysis, source_label = open_synthetic_analysis()
    try:
        if analysis is None:
            print("No ranking analysis to harvest from.")
            return
        candidates = screening_candidates(db, analysis)
        opaque = opaque_index([candidate.application.id for candidate in candidates])

        print(f"Harvesting SCREENING candidates from analysis {analysis.id} ({source_label}) — "
              f"{len(candidates)} current cached screenings. Set expected.fires/absent + note, "
              "drop the HARVEST_ prefix, commit.\n")
        for candidate in candidates:
            app = candidate.application
            idx = opaque[app.id]
            normalized = app.normalized or {}
            produced = [flag.category.value for flag in candidate.report.flags]
            print(json.dumps({
                "key": f"HARVEST_screen_applicant{idx}",
                "metadata": {
                    "note": "SET_ME",
                    "pass": "screening",
                    "expected": {"fires": "SET_ME (categories that MUST fire)", "absent": "SET_ME (over-reach guards)"},
                    "observed_flags": produced,  # what the run flagged — a hint for fires/absent, NOT the label
                    "source": f"{source_label}, analysis {analysis.id}, applicant idx {idx}",
                },
                "given": {
                    "fields": {k: normalized.get(k) for k in _FIELD_KEYS},
                    "essays": _essays_by_column(app.raw_row or {}),
                },
            }, indent=2, ensure_ascii=False))
    finally:
        db.close()


if __name__ == "__main__":
    main()
