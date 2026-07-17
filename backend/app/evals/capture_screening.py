"""Propose screening-flag defensibility eval cases from a run's cached flags — GUARD-GATED.

Screening flags cite applicant essay/field text (the flag's ``evidence``), so — like
score-defensibility — a committable case must come from a synthetic pool. Same guard
(``synthetic_guard.require_synthetic_pool``), same discipline: this proposes opaque-indexed
candidates; a human labels ``expected`` (FLAG_SUPPORTED / FLAG_UNSUPPORTED) + rationale
before they enter ``judge_cases.json``. See ``docs/score-defensibility-design.md`` — the
screening category is the same applicant-text-facing pattern, one pass over.

    python -m app.evals.capture_screening            # propose from the current run
    python -m app.evals.capture_screening --limit 20
"""

from __future__ import annotations

import argparse
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.screening import KIND as SCREENING_KIND
from app.ai.screening import _pet_policy_line
from app.db.models import ApplicationAIResult, RankingRun
from app.evals.capture_scores import _opaque_index
from app.evals.synthetic_guard import require_synthetic_pool
from app.services.ranking_run import get_current_run
from app.services.settings import get_app_settings


def propose_cases(db: Session, run: RankingRun, *, limit: int | None = None) -> list[dict]:
    """Build unlabelled candidate screening-flag defensibility cases from cached flags.

    Guard-gated (raises on a non-synthetic pool). One candidate PER FLAG (a screening row
    holds a list), carrying the flag's category/severity/summary and its cited evidence —
    exactly what the judge needs to rule FLAG_SUPPORTED/FLAG_UNSUPPORTED — plus the opaque
    applicant index and ``evidence_source`` for re-verification. No applicant id or name.
    """
    sheet_id = require_synthetic_pool(db, run)

    # The RESOLVED pet policy the screening pass was actually given (from settings). The
    # judge must see this, not just whatever the flag's evidence happened to quote —
    # fidelity rule: judge sees what production saw. Critical for pet_policy flags, where
    # e.g. `allow_other_pets=False` means the pass was told "no other/exotic pets", so a
    # rabbit IS a violation even though the flag's quote may only mention dogs/cats.
    pet_policy = _pet_policy_line(get_app_settings(db))

    rows = list(
        db.scalars(select(ApplicationAIResult).where(ApplicationAIResult.kind == SCREENING_KIND))
    )
    opaque = _opaque_index([r.application_id for r in rows])

    cases: list[dict] = []
    for r in rows:
        idx = opaque[r.application_id]
        for i, flag in enumerate((r.output or {}).get("flags", [])):
            evidence = {
                "flag_category": flag.get("category"),
                "flag_severity": flag.get("severity"),
                "flag_summary": flag.get("summary"),
                "cited_evidence": flag.get("evidence", ""),
            }
            # Pet-policy flags are judged against the policy — include the real one so the
            # judge isn't ruling on a partial policy the flag's quote happened to name.
            if flag.get("category") == "pet_policy":
                evidence["co_op_pet_policy"] = pet_policy
            cases.append({
                "key": f"screen_{flag.get('category')}_applicant{idx}_{i}__RELABEL",
                "pass": "screening",
                "title": f"[LABEL ME] {flag.get('category')} flag on applicant {idx}",
                "task": "Given the screening flag and its cited evidence (plus any stated policy), decide whether the flag is FLAG_SUPPORTED or FLAG_UNSUPPORTED by that evidence.",
                "evidence": evidence,
                "expected": "SET_ME: flag_supported | flag_unsupported",
                "label_rationale": "SET_ME: why the cited evidence does (or doesn't) warrant this flag.",
                "evidence_source": f"synthetic-pool sheet {sheet_id}, run {run.id}, applicant idx {idx}",
            })
    if limit is not None:
        cases = cases[:limit]
    return cases


def main() -> None:
    parser = argparse.ArgumentParser(description="Propose screening-flag eval cases (guard-gated).")
    parser.add_argument("--limit", type=int, default=None, help="Max candidate flags to emit")
    args = parser.parse_args()

    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        run = get_current_run(db)
        if run is None:
            raise SystemExit("No ranking run to capture from — run a Rank first.")
        cases = propose_cases(db, run, limit=args.limit)
    finally:
        db.close()

    print(json.dumps({"cases": cases}, indent=2))
    print(
        f"\n# {len(cases)} candidate(s). UNLABELLED — set `expected` + `label_rationale`, "
        "rename the key,\n# and move the diagnostic ones into app/evals/fixtures/judge_cases.json.",
    )


if __name__ == "__main__":
    main()
