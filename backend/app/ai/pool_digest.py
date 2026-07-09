"""Shared compressed pool view for the pool-level AI passes (discovery and
reconcile).

Both passes reason over the whole eligible pool in one call and need the *same*
compact per-candidate view — structured facts plus an essay digest (falling back
to raw essays). Defined once here so the two passes provably read the identical
pool, the same anti-drift discipline ``applicant_facts.py`` enforces between
discovery and scoring: a change to what the pool looks like changes it for both
passes at once, never one without the other.

Compressed, not raw essays: the essay-analysis summary is already cross-cut and
short, so the whole pool fits a single call. ``evidence`` is dropped (it is the
grounding quotes, not signal the pool-level judgment needs).
"""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.applicant_facts import applicant_facts
from app.ai.essay_analysis import KIND as ESSAY_ANALYSIS_KIND
from app.ai.schemas import EssayAnalysisReport
from app.db.models import Application, ApplicationAIResult
from app.services.application_import import extract_essays

# Rough per-candidate input token weight for the pre-run cost estimate only (the
# real call is priced from actual usage). Tuned to the SPEC's observed ~$0.07-0.11
# for a ~32-candidate pool on the synthesis model. Shared so discovery and reconcile
# — which send the identical digest — estimate their pool input the same way.
INPUT_TOKENS_PER_CANDIDATE = 600


def essay_reports(db: Session, application_ids: list[int]) -> dict[int, dict]:
    """Most recent essay-analysis output per application, as raw JSON dicts.

    The pool passes prefer this digest over raw essays (shorter, already cross-cut);
    applications without one fall back to raw essays in the prompt.
    """
    if not application_ids:
        return {}
    query = (
        select(ApplicationAIResult)
        .where(ApplicationAIResult.kind == ESSAY_ANALYSIS_KIND)
        .where(ApplicationAIResult.application_id.in_(application_ids))
        .order_by(ApplicationAIResult.created_at)
    )
    latest: dict[int, dict] = {}
    for result in db.scalars(query):
        latest[result.application_id] = result.output
    return latest


def candidate_digest(application: Application, essay_report: dict | None) -> dict:
    """One candidate's contribution to a pool prompt: structured facts plus the
    essay digest (falling back to raw essays), kept compact so the whole pool fits
    one call. Facts and essays together surface both quantitative and qualitative
    axes.
    """
    digest: dict[str, object] = {
        "applicant_id": application.id,
        "facts": applicant_facts(application),
    }
    if essay_report is not None:
        # Validate-and-redump so a stale stored shape can't poison the prompt.
        report = EssayAnalysisReport.model_validate(essay_report)
        digest["essay_analysis"] = report.model_dump(mode="json", exclude={"evidence"})
    else:
        essays = extract_essays(application.raw_row or {})
        digest["essays"] = [
            {"label": e.get("label"), "answer": e.get("answer")} for e in essays
        ]
    return digest


def pool_digest_block(db: Session, applications: list[Application]) -> str:
    """The full ``<applicant_pool>`` prompt block for a pool-level pass: every
    application's compact digest, as pretty JSON wrapped in the XML tag.
    """
    reports = essay_reports(db, [app.id for app in applications])
    digests = [candidate_digest(app, reports.get(app.id)) for app in applications]
    pool_json = json.dumps(digests, indent=2, default=str)
    return f"<applicant_pool>\n{pool_json}\n</applicant_pool>"
