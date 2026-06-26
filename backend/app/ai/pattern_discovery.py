"""Pattern discovery: the pool-level pass that finds how THIS applicant pool varies
(SPEC "Pattern Discovery And Dimension Scoring").

A single synthesis call over the whole eligible pool, producing run-scoped output
(the differentiating dimensions), so it bypasses the ``screen_applications`` engine
and the per-application cache. It reads each candidate's essay-analysis report
(preferred) plus a trimmed view of their raw essays, on the synthesis model.

The model describes the axes, never ranks anyone; scoring and ranking build on top.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.applicant_facts import FILTERED_FACTS_NOTE, applicant_facts
from app.ai.essay_analysis import KIND as ESSAY_ANALYSIS_KIND
from app.ai.prompt_fragments import PROTECTED_CHARACTERISTICS_NOTE
from app.ai.pricing import cost_usd
from app.ai.provider import AIProvider, DeltaSink, Usage
from app.ai.schemas import EssayAnalysisReport, PoolPatternReport
from app.db.models import Application, ApplicationAIResult, ApplicationStatus
from app.schemas.settings import AppSettings
from app.services.application_import import extract_essays


@dataclass(frozen=True)
class DiscoverySeeds:
    """Axes the committee asked discovery to strongly consider (not a mandate).

    ``favourited`` are existing dimensions to keep across re-runs, sent as their
    current name + definition. ``proposed`` are free-text descriptions a member
    wrote. Both are folded into the prompt the same way; the model may refine,
    split, merge, or skip them, and flags each dimension it creates from a request
    with ``from_committee_request`` so the caller can auto-favourite it.
    """

    favourited: list[dict[str, str]] = field(default_factory=list)  # {name, definition}
    proposed: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.favourited and not self.proposed

# Rough per-candidate token weight for the pre-run estimate only (the real call is
# priced from actual usage). Tuned to the SPEC's observed ~$0.07-0.11 for a
# ~32-candidate pool on the synthesis model.
_DISCOVERY_INPUT_TOKENS_PER_CANDIDATE = 600
_DISCOVERY_OUTPUT_TOKENS = 2000

# Not a cached per-application "kind"; named for the admin debug view / logging.
KIND = "pattern_discovery"

SYSTEM_PROMPT = f"""\
You are helping a housing co-op screening committee understand a pool of applicants as a whole.
Your job is to discover the dimensions on which THIS specific pool meaningfully varies — the axes that actually separate stronger from weaker fit here, not a generic ideal co-op member. Favour a richer set of distinct, non-overlapping axes over a few broad ones, but only where the pool genuinely differentiates. Each axis must capture a single concept; never fuse two ideas into one dimension just to keep the list short.
Ground every dimension in patterns you can see across the applicants' own words.
{PROTECTED_CHARACTERISTICS_NOTE} Never make writing polish or fluency a dimension.
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
    Discovery prefers this digest over raw essays (shorter, already cross-cut);
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


def _candidate_digest(application: Application, essay_report: dict | None) -> dict:
    """One candidate's contribution to the pool prompt: structured facts plus the
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


def _seeds_block(seeds: DiscoverySeeds) -> str:
    """The committee-requested axes, rendered as a prompt section. Empty string when
    there are no seeds, so an un-seeded run's prompt is byte-identical to before.
    """
    if seeds.is_empty():
        return ""
    lines: list[str] = []
    for d in seeds.favourited:
        lines.append(f'- {d["name"]}: {d["definition"]}')
    for text in seeds.proposed:
        lines.append(f"- {text}")
    requested = "\n".join(lines)
    return f"""\

The committee has asked you to STRONGLY CONSIDER the following axes. For each one, include a dimension that captures it — refining the wording, splitting it into several dimensions, or merging overlapping ones as the one-concept-per-dimension rule demands. Omit a requested axis ONLY if this pool genuinely does not vary on it (say so is not required, just leave it out). A requested axis is still bound by every rule above: grounded in the applicants' words, single-concept, neutral, never a protected characteristic. Set ``from_committee_request: true`` on every dimension you create from a request below (and on each piece if you split one); leave it false for axes you discover on your own.

REQUESTED AXES:
{requested}
"""


def build_prompt(db: Session, applications: list[Application], *, seeds: DiscoverySeeds | None = None) -> str:
    reports = _essay_reports(db, [app.id for app in applications])
    digests = [_candidate_digest(app, reports.get(app.id)) for app in applications]

    instructions = f"""\
Below is the full pool of eligible applicants. Each entry has structured "facts" (household make-up, income and its split, employment tenure, real-estate ownership, pets) and a summary of their co-op membership essays.
Discover the dimensions on which this pool genuinely varies and that matter for "fit for Penta" — somewhere between 10 and 30. Draw on BOTH the facts and the essays: quantitative axes (e.g. income mix, employment stability, household-to-unit fit) are as valid as qualitative ones (e.g. participation commitment, co-op values). Surface as many as the pool truly supports: prefer splitting a broad axis into distinct, separately-weighable sub-dimensions (e.g. trade skills vs. financial/admin skills vs. community-building skills) over merging them. But every dimension must be independently meaningful and must not overlap another — do not pad the list to reach a number, and do not invent axes the data does not actually distinguish.

Each dimension must measure exactly ONE thing. The decisive test is OPPOSING EVIDENCE: if a single subject could plausibly score HIGH on one part of a dimension and LOW on another part, you have bundled two axes — split them. To see the test working in a neutral setting unrelated to housing: a restaurant rating called "good value" reads as one idea but fuses (a) price fairness with (b) portion size — an expensive place serving huge plates scores high on one and low on the other, so a single "value" number averages to a misleading "moderate" and HIDES which one actually varies. Two ratings, not one. Apply that same seam-finding to whatever axes THIS pool actually presents — do not import the example's subject matter; it is only there to illustrate the move. Watch for the seam even when a name reads as one idea; a name joining concepts with "&", "and", "/", or a comma is just the most obvious case. A single clear concept per dimension is the goal; the higher cap above exists precisely so you never have to combine to fit.

{FILTERED_FACTS_NOTE}

For each dimension provide:
- key: a stable snake_case identifier (e.g. participation_commitment)
- name: a short committee-facing label
- definition: 1-2 neutral sentences on what it measures
- why_it_differentiates: what actually varies across THESE applicants on this axis

Do NOT assign importance or weight to the dimensions. Discovering which axes exist is your job; deciding how much each matters is the committee's, and they do it later. Treat every dimension as equally important here.

Also write a 2-4 sentence neutral summary of what most distinguishes strong from weak fit across this pool.

Do not score or name individual applicants. Describe the axes, not the people."""

    seeds_block = _seeds_block(seeds) if seeds is not None else ""
    pool_json = json.dumps(digests, indent=2, default=str)
    return f"{instructions}{seeds_block}\n\nAPPLICANT POOL:\n{pool_json}"


def estimate_discovery(applications: list[Application], settings: AppSettings) -> float:
    """Projected cost of the single discovery call, scaled by pool size. Discovery
    is uncached, so there's nothing to net out — a straight estimate folded into
    the combined Rank projection.
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
    seeds: DiscoverySeeds | None = None,
    on_delta: DeltaSink | None = None,
) -> tuple[PoolPatternReport, str | None, float]:
    """Run the single pool-level discovery call on the synthesis model. Returns the
    report, the reasoning narrative (kept for the debug view), and the priced cost.

    ``seeds`` are committee-requested axes to strongly consider (favourited +
    proposed); the model flags any dimension it creates from one so the caller can
    auto-favourite it. None/empty means a fully blind discovery (the default).

    ``on_delta``, when given, streams the model's reasoning text as it generates —
    the live "thinking" for this otherwise-opaque multi-minute call. The result is
    identical either way.
    """
    model_id = settings.ai.synthesis_model
    result = provider.structured_output(
        model_id=model_id,
        schema=PoolPatternReport,
        prompt=build_prompt(db, applications, seeds=seeds),
        system_prompt=SYSTEM_PROMPT,
        on_delta=on_delta,
    )
    return result.output, result.narrative, cost_usd(result.model_id, result.usage)
