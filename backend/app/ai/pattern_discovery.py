"""Pattern discovery: the pool-level pass that finds how THIS applicant pool varies
(SPEC "Pattern Discovery And Dimension Scoring").

K parallel synthesis calls over the whole eligible pool (``discover_patterns_fanout``,
SPEC "Fan-Out Redesign"), producing run-scoped output (the differentiating dimensions),
so it bypasses the ``screen_applications`` engine and the per-application cache. Each
reads each candidate's essay-analysis report (preferred) plus a trimmed view of their
raw essays, on the synthesis model. K=1 is a single call; the K reports' cross-call
variation is the diversity a later decomposition step pares to the finest set.

The model describes the axes, never ranks anyone; scoring and ranking build on top.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.analysis import derive_prompt_version
from app.ai.pool_digest import INPUT_TOKENS_PER_CANDIDATE, pool_digest_block
from app.ai.pricing import cost_usd
from app.ai.prompt_fragments import INJECTION_GUARD_NOTE
from app.ai.provider import AIProvider, DeltaSink, Usage
from app.ai.schemas import PoolDimensionReport
from app.db.models import Application, ApplicationStatus
from app.schemas.settings import AppSettings


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

SYSTEM_PROMPT = """\
You are helping a housing co-op screening committee understand a pool of applicants as a whole.
Discover the dimensions on which THIS pool meaningfully varies — the axes that separate stronger from weaker fit here, not a generic ideal member. Favour distinct, non-overlapping axes over a few broad ones, but only where the pool genuinely differentiates; each must capture a single concept — never fuse two to shorten the list.
Ground every dimension in the applicants' own words. Never make writing polish or fluency a dimension.
You describe axes, not individuals; a later step scores and ranks them."""


# Static instruction text. Shared note fragments are interpolated at import.
_INSTRUCTIONS = f"""\
## Task
Discover the dimensions (20-30) on which this pool genuinely varies and that matter for "fit for Penta". Draw on BOTH facts and essays — quantitative axes count as much as qualitative ones. Prefer splitting a broad axis into separately-weighable sub-dimensions over merging. Every dimension must be independently meaningful and non-overlapping.

## Inputs
The eligible applicants are in the `<applicant_pool>` block below — each with structured "facts" (household make-up, income and its split, employment tenure, real-estate ownership, pets) and an essay summary.

## How to judge
- **One concept per dimension.** Test by OPPOSING EVIDENCE: if one applicant could score HIGH on part of a dimension and LOW on another part, it bundles two axes — split them. (Out-of-domain illustration, do not borrow the subject: a restaurant "good value" fuses price fairness with portion size — a pricey place with huge plates is high on one, low on the other, so one "value" number hides which varies. Two ratings, not one.) Watch for the seam even when the name reads as one idea; "&", "and", "/", or a comma is just the obvious case. The high cap exists so you never combine to fit.
- **Do not split applicant vs. co-applicant** (e.g. "applicant's trade skills" vs. "co-applicant's"): assess each concept across both adults jointly. This applies only to that pair — axes about other household members (e.g. children) are fine.
- **Orient so MORE is better fit, with optional splitting:** the high end is the desirable end, since scoring (0..1) always counts a higher score toward fit. Recast a "less is better" axis to its positive form (illustration: "frequency of breakdowns" → "mechanical reliability"). The `definition` must state what is measured and which end is high. But first check whether the OPPOSITE end carries its own legitimate fit story — if both ends do, don't pick the readier one and bury the other; split into two dimensions. It's OK if they are in conflict with each other, the committee will choose the one they want to score and can ignore the other one.
- **A directionless quantity is not a score — reframe it (Goldilocks's sibling).** If a fact varies but neither more nor less is inherently better fit, don't emit a bare 0..1 (uninterpretable; weighting it weights noise). Reframe to the fit concept(s) it *drives*, each oriented more-is-better — emit several, even conflicting (committee picks); drop it if none apply. Don't split the raw number into large/small — a single quantity read two ways won't split. (Illustration, don't borrow the subject: not a "vehicle weight" score but the concepts it drives — "cargo capacity" and "fuel economy".)
- **"Goldilocks" axes** (best value in the middle, both extremes bad): do not score the raw quantity — at the ideal it reads as a misleading "moderate". When the peak comes from ONE quantity judged against a target, reframe to the underlying fit-concept — one naturally more-is-better judgment of how well the applicant matches it (illustration: not "amount of salt" but "seasoned about right"). Eligibility filters exclude most quantity extremes upstream, so this is uncommon.

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
    seeds_block = _seeds_block(seeds) if seeds is not None else ""
    pool_block = pool_digest_block(db, applications)
    return f"{_INSTRUCTIONS}{seeds_block}\n\n{pool_block}"


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

# Output token weight for the pre-run estimate only (input is the shared
# per-candidate pool-digest weight; the real call is priced from actual usage).
# Calibrated to observed spend (2026-07-11): at the 20-30 dimension floor, one
# discovery call emits ~5000 output tokens (each dim carries key/name/definition/
# why + the summary). Was 2000 — set when discovery produced ~14 dims — which
# under-estimated the criteria phase ~2.5x once the floor rose.
_DISCOVERY_OUTPUT_TOKENS = 5000


def estimate_discovery(applications: list[Application], settings: AppSettings) -> float:
    """Projected cost of the single discovery call, scaled by pool size. Discovery
    is uncached, so there's nothing to net out — a straight estimate folded into
    the combined Rank projection.
    """
    usage = Usage(
        input_tokens=INPUT_TOKENS_PER_CANDIDATE * len(applications),
        output_tokens=_DISCOVERY_OUTPUT_TOKENS,
    )
    return cost_usd(settings.ai.discovery_model, usage)


def _discover_from_prompt(
    provider: AIProvider,
    prompt: str,
    settings: AppSettings,
    *,
    on_delta: DeltaSink | None = None,
) -> tuple[PoolDimensionReport, str | None, float]:
    """Make one discovery call from an already-built prompt. Does NO DB work, so it is
    safe to call on a worker thread (the fan-out builds the prompt once on the calling
    thread, then runs this K times in the pool — see ``run_in_pool``'s session-free
    contract). The single place that knows how to shape + price a discovery call.
    """
    result = provider.structured_output(
        model_id=settings.ai.discovery_model,
        schema=PoolDimensionReport,
        prompt=prompt,
        system_prompt=SYSTEM_PROMPT,
        on_delta=on_delta,
    )
    return result.output, result.narrative, cost_usd(result.model_id, result.usage)


@dataclass(frozen=True)
class DiscoveryPass:
    """One of the K fan-out discovery calls: the report it produced and its own
    reasoning narrative (kept per-pass so the Insights panel can show each discoverer,
    not just the one that streamed live)."""

    report: PoolDimensionReport
    narrative: str | None


@dataclass(frozen=True)
class FanOutDiscovery:
    """The result of K parallel discovery calls (SPEC "Fan-Out Redesign", D6).

    ``passes`` are the K fresh-context discoveries (report + its narrative) whose
    cross-call variation is the diversity a later decomposition step pares to the finest
    non-overlapping set. Order is not meaningful (calls complete out of order).
    ``narrative`` is the live-streamed reasoning of ONE representative call (the others
    run silently), kept for the run-level discovery narrative. ``cost_usd`` sums all K.
    """

    passes: list[DiscoveryPass]
    narrative: str | None
    cost_usd: float

    @property
    def reports(self) -> list[PoolDimensionReport]:
        """The K reports, order-agnostic — the input to decomposition."""
        return [p.report for p in self.passes]


def discover_patterns_fanout(
    db: Session,
    provider: AIProvider,
    *,
    applications: list[Application],
    settings: AppSettings,
    k: int,
    seeds: DiscoverySeeds | None = None,
    on_delta: DeltaSink | None = None,
) -> FanOutDiscovery:
    """Run K parallel, identical-prompt discovery calls and collect their reports.

    The K calls share ONE prompt, built once here on the calling thread (a single
    pool-digest DB read); the fan-out itself does NO DB work, so the worker calls are
    session-free as ``run_in_pool`` requires. Their diversity comes from the model's
    nondeterminism across fresh contexts (the same variation the convergence experiment
    measured), not from differing inputs — see D6.

    ``k`` ≥ 1; k=1 is a single call (degenerate fan-out). ``on_delta`` streams only the
    first call's reasoning as the live "thinking"; the rest are silent to keep the
    stream coherent. A worker that raises propagates (the caller treats a failed
    criteria phase as fatal, same as the single-call path).
    """
    from app.ai.analysis import run_in_pool

    # Build the prompt ONCE, here on the calling thread (a single pool-digest DB read).
    # The K worker calls then share it and touch no DB — satisfying run_in_pool's
    # session-free contract (SQLAlchemy sessions aren't thread-safe) and rendering the
    # digest once instead of K times.
    prompt = build_prompt(db, applications, seeds=seeds)

    def _call(index: int) -> tuple[PoolDimensionReport, str | None, float]:
        # Only worker 0 streams; interleaving K reasoning traces is unreadable.
        return _discover_from_prompt(
            provider, prompt, settings, on_delta=on_delta if index == 0 else None
        )

    passes: list[DiscoveryPass] = []
    live_narrative: str | None = None
    total_cost = 0.0
    for index, outcome, error in run_in_pool(
        list(range(k)), call=_call, max_workers=min(k, settings.ai.max_workers)
    ):
        if error is not None:
            raise error
        report, narrative, cost = outcome
        # Pair each report with its OWN narrative (not by completion order) so the
        # per-discoverer panel shows the right reasoning next to the right dimensions.
        passes.append(DiscoveryPass(report=report, narrative=narrative))
        if index == 0:
            live_narrative = narrative  # the one that streamed as live "thinking"
        total_cost += cost

    return FanOutDiscovery(passes=passes, narrative=live_narrative, cost_usd=total_cost)
