"""Propose SCREENING golden-case candidates from a real run's cached screening flags.

A screening golden case freezes one synthetic applicant, runs it through the real screening
prompt, and grades the produced flag categories per-category (``expected.fires`` must appear,
``expected.absent`` must not). This mines the newest run's cached screening results for
candidates, each emitted as an EXACT slice of the input that run screened (the same 7 form
fields + 4 essays the pass assembles) in the current golden envelope, with the flags the run
produced shown as a labelling hint. Guard-gated to synthetic pools; PROPOSES only — a human
sets ``expected.fires``/``absent`` + note and drops the HARVEST_ prefix before committing.
See scripts/_harvest_common.py.

    python -m scripts.harvest_screening_cases        # from backend/
"""

from __future__ import annotations

import json

from app.ai.screening import KIND as SCREENING_KIND
from app.services.application_import import ESSAY_FIELDS
from scripts._harvest_common import opaque_index, open_synthetic_run

# The exact fields the screening pass sends (see app/ai/screening.build_prompt) — kept in the
# same order so a harvested `given` is byte-for-byte the input production saw.
_FIELD_KEYS = (
    "applicant_name", "co_applicant_name", "child_details", "pets_text",
    "applicant_email", "co_applicant_email", "co_applicant_phone",
)


def _essays_by_column(raw_row: dict) -> dict[str, str]:
    """Essays keyed by their form-question column — the shape the golden `given.essays` uses
    (the eval feeds it as an applicant's raw_row, and the screening prompt reads each answer by
    column). Mirrors extract_essays' column lookup, but as a dict, not the list the live pass
    uses internally."""
    return {column: str(raw_row.get(column, "") or "").strip() for _label, column in ESSAY_FIELDS}


def main() -> None:
    from sqlalchemy import select

    from app.db.models import Application, ApplicationAIResult

    db, run, sheet_id = open_synthetic_run()
    try:
        if run is None:
            print("No ranking run to harvest from.")
            return
        rows = list(db.scalars(select(ApplicationAIResult).where(ApplicationAIResult.kind == SCREENING_KIND)))
        apps = {a.id: a for a in db.scalars(select(Application))}
        opaque = opaque_index([r.application_id for r in rows])

        print(f"Harvesting SCREENING candidates from run {run.id} (synthetic sheet {sheet_id}) — "
              f"{len(rows)} cached screenings. Set expected.fires/absent + note, drop the HARVEST_ prefix, commit.\n")
        for r in rows:
            app = apps.get(r.application_id)
            if app is None:
                continue
            idx = opaque[r.application_id]
            normalized = app.normalized or {}
            produced = [f.get("category") for f in (r.output or {}).get("flags", [])]
            print(json.dumps({
                "key": f"HARVEST_screen_applicant{idx}",
                "metadata": {
                    "note": "SET_ME",
                    "pass": "screening",
                    "expected": {"fires": "SET_ME (categories that MUST fire)", "absent": "SET_ME (over-reach guards)"},
                    "observed_flags": produced,  # what the run flagged — a hint for fires/absent, NOT the label
                    "source": f"synthetic sheet {sheet_id}, run {run.id}, applicant idx {idx}",
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
