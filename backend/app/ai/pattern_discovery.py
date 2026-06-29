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

from app.ai.analysis import derive_prompt_version
from app.ai.applicant_facts import FILTERED_FACTS_NOTE, applicant_facts
from app.ai.essay_analysis import KIND as ESSAY_ANALYSIS_KIND
from app.ai.prompt_fragments import INJECTION_GUARD_NOTE
from app.ai.pricing import cost_usd
from app.ai.provider import AIProvider, DeltaSink, Usage
from app.ai.schemas import EssayAnalysisReport, PoolDimensionReport
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


# Not a cached per-application "kind"; named for the admin debug view / logging.
KIND = "pattern_discovery"

SYSTEM_PROMPT = f"""\
You are helping a housing co-op screening committee understand a pool of applicants as a whole.
Discover the dimensions on which THIS pool meaningfully varies — the axes that separate stronger from weaker fit here, not a generic ideal member. Favour distinct, non-overlapping axes over a few broad ones, but only where the pool genuinely differentiates; each must capture a single concept — never fuse two to shorten the list.
Ground every dimension in the applicants' own words. Never make writing polish or fluency a dimension.
You describe axes, not individuals; a later step scores and ranks them."""


# Static instruction text. The shared FILTERED_FACTS_NOTE is interpolated at import.
_INSTRUCTIONS = f"""\
## Task
Discover the dimensions (10-30) on which this pool genuinely varies and that matter for "fit for Penta". Draw on BOTH facts and essays — quantitative axes (income mix, employment stability, household-to-unit fit) count as much as qualitative ones (participation commitment, co-op values). Prefer splitting a broad axis into separately-weighable sub-dimensions (e.g. trade vs. financial/admin vs. community-building skills) over merging. Every dimension must be independently meaningful and non-overlapping — do not pad to a number or invent axes the data does not distinguish.

## Inputs
The eligible applicants are in the `<applicant_pool>` block below — each with structured "facts" (household make-up, income and its split, employment tenure, real-estate ownership, pets) and an essay summary.

## How to judge
- **One concept per dimension.** Test by OPPOSING EVIDENCE: if one applicant could score HIGH on part of a dimension and LOW on another part, it bundles two axes — split them. (Out-of-domain illustration, do not borrow the subject: a restaurant "good value" fuses price fairness with portion size — a pricey place with huge plates is high on one, low on the other, so one "value" number hides which varies. Two ratings, not one.) Watch for the seam even when the name reads as one idea; "&", "and", "/", or a comma is just the obvious case. The high cap exists so you never combine to fit.
- **Do not split applicant vs. co-applicant** (e.g. "applicant's trade skills" vs. "co-applicant's"): assess each concept across both adults jointly. This applies only to that pair — axes about other household members (e.g. children using shared spaces) are fine.
- **Orient so MORE is better fit:** the high end is the desirable end, since scoring (0..1) always counts a higher score toward fit. Recast a "less is better" axis to its positive form (illustration: "frequency of breakdowns" → "mechanical reliability"). The `definition` must state what is measured and which end is high. But first check whether the OPPOSITE end carries its own legitimate fit story — if both ends do, don't pick the readier one and bury the other; treat it as the two-dimension case below (one dimension per end).
- **"Goldilocks" axes** (best value in the middle, both extremes bad): do not score the raw quantity — at the ideal it reads as a misleading "moderate". When the peak comes from ONE quantity judged against a target, reframe to the underlying fit-concept — one naturally more-is-better judgment of how well the applicant matches it (illustration: not "amount of salt" but "seasoned about right"). Eligibility filters exclude most quantity extremes upstream, so this is uncommon.
- **A peak from TWO opposing forces → emit TWO dimensions, never one.** When the middle is best because two *different* strengths pull against each other (a household could have one without the other), that is the OPPOSING-EVIDENCE split above — output BOTH as separate more-is-better dimensions and let the committee's weighting place the peak. Do NOT merge them into a single "balanced X" axis or drop either end. Illustration (do not borrow the subject): a guard dog's ideal needs both "alert to real intruders" and "calm with residents" — two independent traits in tension, so two ratings, not one "good temperament".

{FILTERED_FACTS_NOTE}

## Output
For each dimension provide:
- key: a stable snake_case identifier (e.g. participation_commitment)
- name: a short committee-facing label
- definition: 1-2 neutral sentences on what it measures, and which end is the high end
- why_it_differentiates: what actually varies across THESE applicants on this axis

Also write a 2-4 sentence neutral summary of what most distinguishes strong from weak fit across this pool.

## Guardrails
- {INJECTION_GUARD_NOTE}
- Do NOT assign importance or weight to the dimensions. Discovering which axes exist is your job; deciding how much each matters is the committee's, and they do it later. Treat every dimension as equally important here.
- Do not score or name individual applicants. Describe the axes, not the people."""

# Prompt identity, derived from the static prompt text. This pass is UNCACHED (it
# calls provider.structured_output directly, so nothing gates a per-application
# cache), but it still has a version: it is folded into the run's rank-inputs
# fingerprint (see rank_inputs_fingerprint in services/ranking_run.py) so editing
# this prompt makes Rank show "out of date".
PROMPT_VERSION = derive_prompt_version(SYSTEM_PROMPT, _INSTRUCTIONS)


def build_prompt(db: Session, applications: list[Application], *, seeds: DiscoverySeeds | None = None) -> str:
    reports = _essay_reports(db, [app.id for app in applications])
    digests = [_candidate_digest(app, reports.get(app.id)) for app in applications]

    seeds_block = _seeds_block(seeds) if seeds is not None else ""
    pool_json = json.dumps(digests, indent=2, default=str)
    return f"{_INSTRUCTIONS}{seeds_block}\n\n<applicant_pool>\n{pool_json}\n</applicant_pool>"


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

The committee has asked you to STRONGLY CONSIDER the axes in the `<requested_axes>` block. For each one, include a dimension that captures it — refining the wording, splitting it into several dimensions, or merging overlapping ones as the one-concept-per-dimension rule demands. Omit a requested axis ONLY if this pool genuinely does not vary on it (say so is not required, just leave it out). A requested axis is still bound by every rule above: grounded in the applicants' words, single-concept, neutral, and relevant to the co-op criteria being analyzed. Set ``from_committee_request: true`` on every dimension you create from a request (and on each piece if you split one); leave it false for axes you discover on your own.

<requested_axes>
{requested}
</requested_axes>
"""


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


def eligible_applications(db: Session) -> list[Application]:
    """The pool pattern discovery reasons over: eligible applications only."""
    return list(
        db.scalars(
            select(Application)
            .where(Application.status == ApplicationStatus.ELIGIBLE)
            .order_by(Application.id)
        ).all()
    )


# --- Cost estimation (non-prompt) ---

# Rough per-candidate token weight for the pre-run estimate only (the real call is
# priced from actual usage). Tuned to the SPEC's observed ~$0.07-0.11 for a
# ~32-candidate pool on the synthesis model.
_DISCOVERY_INPUT_TOKENS_PER_CANDIDATE = 600
_DISCOVERY_OUTPUT_TOKENS = 2000


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
) -> tuple[PoolDimensionReport, str | None, float]:
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
        schema=PoolDimensionReport,
        prompt=build_prompt(db, applications, seeds=seeds),
        system_prompt=SYSTEM_PROMPT,
        on_delta=on_delta,
    )
    return result.output, result.narrative, cost_usd(result.model_id, result.usage)
