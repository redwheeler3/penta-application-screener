"""Propose SCORING golden-case candidates from a real run's cached dimension scores.

A scoring golden case freezes one synthetic applicant + one dimension, runs it through the real
scoring prompt, and checks the produced score lands in the expected ``[score_min, score_max]``
band. This mines the newest run's cached scores for candidate cases, each emitted as an EXACT
slice of the input that run scored (the applicant's facts + essays and the dimension's full
definition/poles) in the current golden envelope — so a committed case reproduces exactly what
production saw. Guard-gated to synthetic pools; PROPOSES only (a human sets the ``expected``
band + note and drops the HARVEST_ prefix before committing). See scripts/_harvest_common.py.

    python -m scripts.harvest_scoring_cases          # from backend/
"""

from __future__ import annotations

import json

from app.ai.applicant_facts import applicant_facts
from app.ai.dimension_scoring import KIND_PREFIX
from app.services.application_import import extract_essays
from scripts._harvest_common import opaque_index, open_synthetic_run


def main() -> None:
    from sqlalchemy import select

    from app.db.models import Application, ApplicationAIResult
    from app.services.analysis import current_dimension_report

    db, run, sheet_id = open_synthetic_run()
    try:
        if run is None:
            print("No ranking run to harvest from.")
            return
        report = current_dimension_report(run)
        dims = {d.key: d for d in report.dimensions} if report else {}

        rows = list(
            db.scalars(select(ApplicationAIResult).where(ApplicationAIResult.kind.startswith(f"{KIND_PREFIX}:")))
        )
        apps = {a.id: a for a in db.scalars(select(Application))}
        opaque = opaque_index([r.application_id for r in rows])

        print(f"Harvesting SCORING candidates from run {run.id} (synthetic sheet {sheet_id}) — "
              f"{len(rows)} cached scores. Set the expected band + note, drop the HARVEST_ prefix, commit.\n")
        for r in rows:
            out = r.output or {}
            key = out.get("dimension_key", "")
            dim = dims.get(key)
            app = apps.get(r.application_id)
            if dim is None or app is None:
                continue  # a score for a dimension not in the settled set (or a missing app) — skip
            idx = opaque[r.application_id]
            print(json.dumps({
                "key": f"HARVEST_score_{key}_applicant{idx}",
                "metadata": {
                    "note": "SET_ME",
                    "pass": "scoring",
                    "expected": {"score_min": "SET_ME", "score_max": "SET_ME", "confidence": "SET_ME (low|medium|high, optional)"},
                    "observed_score": out.get("score"),  # what the run produced — a hint for the band, NOT the label
                    "source": f"synthetic sheet {sheet_id}, run {run.id}, applicant idx {idx}",
                },
                "given": {
                    "applicant": {"facts": applicant_facts(app), "essays": extract_essays(app.raw_row or {})},
                    "dimension": {"key": dim.key, "name": dim.name, "definition": dim.definition,
                                  "high_end": dim.high_end, "low_end": dim.low_end},
                },
            }, indent=2, ensure_ascii=False))
    finally:
        db.close()


if __name__ == "__main__":
    main()
