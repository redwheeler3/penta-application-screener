"""Pattern discovery: the pool-level pass that finds how THIS applicant pool
varies (SPEC "Pattern Discovery And Dimension Scoring", milestone 7).

Unlike the per-application passes (quality flags, essay analysis), this is a
single synthesis call over the *whole* eligible pool. It produces run-scoped
output — the differentiating dimensions and a default weighting — not a
per-candidate result, so it does not go through the ``screen_applications``
engine or the per-application cache. It reads each candidate's essay-analysis
report (preferred) plus a trimmed view of their raw essays, and uses the
synthesis model because this is exactly the cross-document judgment that tier is
reserved for.

The model never ranks anyone here. It describes the axes; per-candidate scoring
and (later) deterministic ranking build on top.
"""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.essay_analysis import KIND as ESSAY_ANALYSIS_KIND
from app.ai.pricing import cost_usd
from app.ai.provider import AIProvider
from app.ai.schemas import EssayAnalysisReport, PoolPatternReport
from app.db.models import Application, ApplicationAIResult, ApplicationStatus
from app.schemas.settings import AppSettings
from app.services.application_import import extract_essays

# Not a cached per-application "kind"; named for the admin debug view / logging.
KIND = "pattern_discovery"

SYSTEM_PROMPT = """\
You are helping a housing co-op screening committee understand a pool of applicants as a whole.
Your job is to discover the few dimensions on which THIS specific pool meaningfully varies — the axes that actually separate stronger from weaker fit here, not a generic ideal co-op member.
Ground every dimension in patterns you can see across the applicants' own words.
Stay neutral and evidence-based; never use protected characteristics, writing polish, or fluency as a dimension.
You do not rank or score individual applicants; a later step does that."""


def eligible_applications(db: Session) -> list[Application]:
    """The pool pattern discovery reasons over: eligible applications only."""
    return list(
        db.scalars(
            select(Application)
            .where(Application.status == ApplicationStatus.ELIGIBLE)
            .order_by(Application.id)
        ).all()
    )


def _essay_reports(db: Session, application_ids: list[int]) -> dict[int, dict]:
    """Most recent essay-analysis output per application, as raw JSON dicts.

    Pattern discovery prefers the normalized essay-analysis digest over raw
    essays — it is shorter and already cross-cut into stable fields. Applications
    without an essay-analysis result fall back to their raw essays in the prompt.
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


def _candidate_digest(application: Application, essay_report: dict | None) -> dict:
    """One candidate's contribution to the pool prompt: prefer the essay digest,
    fall back to raw essays. Kept compact so the whole pool fits one call.
    """
    if essay_report is not None:
        # Validate-and-redump so a stale stored shape can't poison the prompt.
        report = EssayAnalysisReport.model_validate(essay_report)
        return {
            "applicant_id": application.id,
            "essay_analysis": report.model_dump(mode="json", exclude={"evidence"}),
        }
    essays = extract_essays(application.raw_row or {})
    return {
        "applicant_id": application.id,
        "essays": [
            {"label": e.get("label"), "answer": e.get("answer")} for e in essays
        ],
    }


def build_prompt(db: Session, applications: list[Application]) -> str:
    reports = _essay_reports(db, [app.id for app in applications])
    digests = [_candidate_digest(app, reports.get(app.id)) for app in applications]

    instructions = """\
Below is the full pool of eligible applicants, each summarized from their co-op membership essays.
Discover the few dimensions on which this pool genuinely varies and that matter for "fit for Penta" — typically 4 to 7. Fewer, sharper dimensions are better than many overlapping ones.

For each dimension provide:
- key: a stable snake_case identifier (e.g. participation_commitment)
- name: a short committee-facing label
- definition: 1-2 neutral sentences on what it measures
- why_it_differentiates: what actually varies across THESE applicants on this axis
- default_weight: a starting importance 0..1 toward overall fit (the committee will re-weight later)

Also write a 2-4 sentence neutral summary of what most distinguishes strong from weak fit across this pool.

Do not score or name individual applicants. Describe the axes, not the people."""

    pool_json = json.dumps(digests, indent=2, default=str)
    return f"{instructions}\n\nAPPLICANT POOL:\n{pool_json}"


def discover_patterns(
    db: Session,
    provider: AIProvider,
    *,
    applications: list[Application],
    settings: AppSettings,
) -> tuple[PoolPatternReport, str | None, float]:
    """Run the single pool-level discovery call on the synthesis model.

    Returns the report, the model's reasoning narrative (kept for the debug
    view), and the priced cost of the call.
    """
    model_id = settings.ai.synthesis_model
    result = provider.structured_output(
        model_id=model_id,
        schema=PoolPatternReport,
        prompt=build_prompt(db, applications),
        system_prompt=SYSTEM_PROMPT,
    )
    return result.output, result.narrative, cost_usd(result.model_id, result.usage)
