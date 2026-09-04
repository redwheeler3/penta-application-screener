"""Propose SCORING golden-case candidates from a synthetic analysis's dimension scores.

A scoring golden case freezes one synthetic applicant + one dimension, runs it through the real
scoring prompt, and checks the produced score lands in the expected ``[score_min, score_max]``
band. This reconstructs the current cache identity for the newest analysis's opening,
applications, dimensions, model, reasoning, and prompt. Each cache hit is emitted as an EXACT
slice of the model input (the applicant's facts + essays and the dimension's full
definition/poles) in the current golden envelope. Guard-gated by the analysis's persisted
synthetic provenance; PROPOSES only (a human sets the ``expected`` band + note and drops the
HARVEST_ prefix before committing). See scripts/_harvest_common.py.

    python -m scripts.harvest_scoring_cases                       # from backend/
    python -m scripts.harvest_scoring_cases --max-abs-score 0.15  # near-neutral only
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.ai.analysis import cached_outcome
from app.ai.applicant_facts import applicant_facts
from app.ai.dimension_scoring import (
    PROMPT_VERSION,
    applications_to_score,
    kind_for_dimension,
)
from app.ai.schemas import DimensionScore, PoolDimension
from app.db.models import Analysis, Application
from app.schemas.settings import effective_reasoning_effort
from app.services.application_content import extract_essays
from app.services.ranking.dimensions import current_dimension_report
from app.services.settings import get_app_settings
from scripts._harvest_common import opaque_index, open_synthetic_analysis


@dataclass(frozen=True)
class ScoringCandidate:
    application: Application
    dimension: PoolDimension
    score: DimensionScore


def scoring_candidates(db: Session, analysis: Analysis) -> list[ScoringCandidate]:
    """Return only current-input cache hits for the analysis's opening and dimensions.

    The score cache spans every historical analysis. Reconstructing the current cache key is
    therefore essential: filtering only by dimension kind can silently attribute an old model,
    prompt, applicant revision, or out-of-pool row to the selected analysis.
    """
    if analysis.opening_id is None:
        return []
    report = current_dimension_report(analysis)
    if report is None:
        return []
    applications = applications_to_score(db, analysis.opening_id)

    settings = get_app_settings(db)
    model_id = settings.ai.dimension_scoring_model
    reasoning_effort = effective_reasoning_effort(
        model_id, settings.ai.dimension_scoring_reasoning_effort
    )
    candidates: list[ScoringCandidate] = []
    for application in applications:
        for dimension in report.dimensions:
            outcome = cached_outcome(
                db,
                application,
                kind=kind_for_dimension(dimension.key),
                schema=DimensionScore,
                model_id=model_id,
                prompt_version=PROMPT_VERSION,
                reasoning_effort=reasoning_effort,
            )
            if outcome is not None:
                candidates.append(ScoringCandidate(application, dimension, outcome.output))
    return candidates


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--max-abs-score",
        type=float,
        help="Show only candidates whose observed score is this close to neutral (0).",
    )
    args = parser.parse_args()

    db, analysis, source_label = open_synthetic_analysis()
    try:
        if analysis is None:
            print("No ranking analysis to harvest from.")
            return
        candidates = scoring_candidates(db, analysis)
        opaque = opaque_index([candidate.application.id for candidate in candidates])
        if args.max_abs_score is not None:
            candidates = [
                candidate
                for candidate in candidates
                if abs(candidate.score.score) <= args.max_abs_score
            ]

        print(f"Harvesting SCORING candidates from analysis {analysis.id} ({source_label}) — "
              f"{len(candidates)} current cached scores. Set the expected band + note, "
              "drop the HARVEST_ prefix, commit.\n")
        for candidate in candidates:
            app = candidate.application
            dim = candidate.dimension
            out = candidate.score.model_dump(mode="json")
            idx = opaque[app.id]
            print(json.dumps({
                "key": f"HARVEST_score_{dim.key}_applicant{idx}",
                "metadata": {
                    "note": "SET_ME",
                    "pass": "scoring",
                    "expected": {"score_min": "SET_ME", "score_max": "SET_ME", "confidence": "SET_ME (low|medium|high, optional)"},
                    # The current cache hit is a labelling hint, never the human label.
                    "observed_score": out.get("score"),
                    "source": f"{source_label}, analysis {analysis.id}, applicant idx {idx}",
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
