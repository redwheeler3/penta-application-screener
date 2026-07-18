"""Propose score-defensibility eval cases from a run's cached scores — GUARD-GATED.

Score-defensibility judges whether a dimension score is warranted by the applicant's
cited evidence. Building such a case means committing that evidence quote, which is only
safe when the pool is synthetic — so this refuses any run whose source sheet is not on the
synthetic allowlist (``synthetic_guard.require_synthetic_pool``). See
``docs/score-defensibility-design.md``.

This *proposes* candidates only. A human picks the diagnostic ones (an overclaim, a
defensible one, an absence-as-presence) and writes the ``expected`` verdict +
``label_rationale`` before they enter ``judge_cases.json`` — capture never labels.

``propose_cases`` is invoked from the AI Quality tab's "Harvest from current run" action
(``GET /evals/harvest/scoring``); there is no CLI entry point.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.dimension_scoring import KIND_PREFIX
from app.db.models import ApplicationAIResult, RankingRun
from app.evals.synthetic_guard import require_synthetic_pool
from app.services.ranking_run import current_dimension_report


def _opaque_index(application_ids: list[int]) -> dict[int, int]:
    """Stable application_id -> opaque 0-based index (sorted), so a proposed case names
    the applicant only by position — never the real id, matching the fixture's rule."""
    return {aid: i for i, aid in enumerate(sorted(set(application_ids)))}


def propose_cases(db: Session, run: RankingRun, *, limit: int | None = None) -> list[dict]:
    """Build unlabelled candidate score-defensibility cases from ``run``'s cached scores.

    Caller must have passed the synthetic guard already; ``evidence_source`` records the
    sheet id + run so the committed case is re-verifiable. Each candidate carries the
    dimension definition + poles, the applicant's cited evidence, and the score under
    test — exactly what the judge needs to rule SUPPORTED/UNSUPPORTED, and nothing that
    identifies the applicant beyond the (synthetic) quote and an opaque index.
    """
    sheet_id = require_synthetic_pool(db, run)  # the gate — raises on a non-synthetic pool

    report = current_dimension_report(run)
    dims = {d.key: d for d in report.dimensions} if report else {}

    rows = list(
        db.scalars(
            select(ApplicationAIResult).where(
                ApplicationAIResult.kind.startswith(f"{KIND_PREFIX}:")
            )
        )
    )
    opaque = _opaque_index([r.application_id for r in rows])

    cases: list[dict] = []
    for r in rows:
        out = r.output or {}
        key = out.get("dimension_key", "")
        dim = dims.get(key)
        if dim is None:
            continue  # a score for a dimension not in the current settled set — skip
        idx = opaque[r.application_id]
        cases.append({
            "key": f"score_{key}_applicant{idx}__RELABEL",
            # metadata: harness-only, never sent to the judge (the human fills SET_ME fields).
            "metadata": {
                "pass": "scoring",
                "title": f"[LABEL ME] score {out.get('score')} on {key} for applicant {idx}",
                "expected": "SET_ME: supported | unsupported",
                "label_rationale": "SET_ME: why this score is (un)supported by the cited evidence.",
                "evidence_source": f"synthetic-pool sheet {sheet_id}, run {run.id}, applicant idx {idx}",
            },
            # evidence + prompt: exactly what the judge sees.
            "evidence": {
                "dimension": key,
                "dimension_definition": dim.definition,
                "high_end": dim.high_end,
                "low_end": dim.low_end,
                "cited_evidence": out.get("evidence", ""),
                "score": out.get("score"),
            },
            "prompt": {
                "question": "Given the dimension and the applicant's cited evidence, decide whether the score is SUPPORTED or UNSUPPORTED by that evidence.",
            },
        })
    if limit is not None:
        cases = cases[:limit]
    return cases
