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

from app.ai.applicant_facts import FILTERED_FACTS_NOTE, applicant_facts
from app.ai.essay_analysis import KIND as ESSAY_ANALYSIS_KIND
from app.ai.pricing import cost_usd
from app.ai.provider import AIProvider, Usage
from app.ai.schemas import EssayAnalysisReport, PoolPatternReport
from app.db.models import Application, ApplicationAIResult, ApplicationStatus
from app.schemas.settings import AppSettings
from app.services.application_import import extract_essays

# Rough per-candidate token weight of the discovery prompt (each candidate's
# facts + essay digest) plus the single structured report. Discovery is one
# pool-level call, so its cost scales with pool size; these feed the pre-run
# estimate only (the real call is priced from actual usage). Tuned to the SPEC's
# observed ~$0.07-0.11 range for a ~32-candidate pool on the synthesis model.
_DISCOVERY_INPUT_TOKENS_PER_CANDIDATE = 600
_DISCOVERY_OUTPUT_TOKENS = 2000

# Not a cached per-application "kind"; named for the admin debug view / logging.
KIND = "pattern_discovery"

SYSTEM_PROMPT = """\
You are helping a housing co-op screening committee understand a pool of applicants as a whole.
Your job is to discover the dimensions on which THIS specific pool meaningfully varies — the axes that actually separate stronger from weaker fit here, not a generic ideal co-op member. Favour a richer set of distinct, non-overlapping axes over a few broad ones, but only where the pool genuinely differentiates.
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
    """One candidate's contribution to the pool prompt: the structured facts plus
    the essay digest (falling back to raw essays). Kept compact so the whole pool
    fits one call. Facts and essays together let the model discover both
    quantitative axes (income mix, household fit, tenure) and qualitative ones.
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


def build_prompt(db: Session, applications: list[Application]) -> str:
    reports = _essay_reports(db, [app.id for app in applications])
    digests = [_candidate_digest(app, reports.get(app.id)) for app in applications]

    instructions = f"""\
Below is the full pool of eligible applicants. Each entry has structured "facts" (household make-up, income and its split, employment tenure, real-estate ownership, pets) and a summary of their co-op membership essays.
Discover the dimensions on which this pool genuinely varies and that matter for "fit for Penta" — somewhere between 5 and 25. Draw on BOTH the facts and the essays: quantitative axes (e.g. income mix, employment stability, household-to-unit fit) are as valid as qualitative ones (e.g. participation commitment, co-op values). Surface as many as the pool truly supports: prefer splitting a broad axis into distinct, separately-weighable sub-dimensions (e.g. trade skills vs. financial/admin skills vs. community-building skills) over merging them. But every dimension must be independently meaningful and must not overlap another — do not pad the list to reach a number, and do not invent axes the data does not actually distinguish.

{FILTERED_FACTS_NOTE}

For each dimension provide:
- key: a stable snake_case identifier (e.g. participation_commitment)
- name: a short committee-facing label
- definition: 1-2 neutral sentences on what it measures
- why_it_differentiates: what actually varies across THESE applicants on this axis

Do NOT assign importance or weight to the dimensions. Discovering which axes exist is your job; deciding how much each matters is the committee's, and they do it later. Treat every dimension as equally important here.

Also write a 2-4 sentence neutral summary of what most distinguishes strong from weak fit across this pool.

Do not score or name individual applicants. Describe the axes, not the people."""

    pool_json = json.dumps(digests, indent=2, default=str)
    return f"{instructions}\n\nAPPLICANT POOL:\n{pool_json}"


def estimate_discovery(applications: list[Application], settings: AppSettings) -> float:
    """Projected cost of the single discovery call, scaled by pool size.

    Discovery is uncached and always re-runs, so there is no per-candidate cache
    to net out (unlike the per-application passes) — this is a straight estimate
    used only to fold discovery into the combined Rank cost projection.
    """
    usage = Usage(
        input_tokens=_DISCOVERY_INPUT_TOKENS_PER_CANDIDATE * len(applications),
        output_tokens=_DISCOVERY_OUTPUT_TOKENS,
    )
    return cost_usd(settings.ai.synthesis_model, usage)


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
