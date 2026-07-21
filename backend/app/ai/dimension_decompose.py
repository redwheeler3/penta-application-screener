"""Dimension decomposition: distil K parallel discovery reports into the finest set
of axes that are each genuinely differentiating AND mutually non-overlapping
(SPEC "Fan-Out Redesign", Phase 3 — the single-call baseline variant).

K fresh-context discovery calls carve the same pool at different, overlapping
granularities (the diversity Phase 2 produces). This step sees all K at once and
settles ONE non-overlapping set. Seeing every carving together is what lets it answer
"is this axis redundant with one we already have?" — decidable by comparison, unlike
"does the pool vary on this?", which is unfalsifiable (discovery only ever coins an
axis because it saw variance; see the convergence case study).

The failure is two-sided and the prompt must guard both:
  - UNDER-merge: keep nine "participation" re-carvings → the committee unknowingly
    weights one concept 9×.
  - OVER-merge: collapse a nurse's health-safety into a treasurer's finance → the
    committee loses a lever it needed. This is the higher-stakes error (a lost axis
    is invisible downstream), so the bar to MERGE is high, not the bar to split.

The two forces are given falsifiable tests, mirroring the discovery one-concept rule
and the match pass's identity bar: to MERGE two axes you must assert they'd score the
same applicant the same way AND same direction; to KEEP two apart you must be able to name
an applicant high on one and low on the other. Inverses (opposite poles of one spectrum)
fail the merge test and pass the keep test for every applicant, so they are KEEP — the
direction clause stops the model folding them as "the same axis, just reversed" and burying
one orientation. Committee-requested axes get extra protection (D9): never merged away
silently — the flag rides through and the decision must say so.

This single structured call is the decomposition step, wired into ``rank_run``.
"""

from __future__ import annotations

import json

from app.ai.analysis import derive_prompt_version
from app.ai.pricing import PassCost, cost_usd
from app.ai.prompt_fragments import INJECTION_GUARD_NOTE
from app.ai.provider import AIProvider, DeltaSink, Usage
from app.ai.schemas import (
    DecomposedDimension,
    DecompositionReport,
    PoolDimension,
    PoolDimensionReport,
)
from app.schemas.settings import AppSettings

# Bedrock read timeout (s) for the decomposition call specifically. It streams a large
# reasoned set (settle ~250 input dims → ~28 axes, each with merge reasoning) that blows
# the provider's 120s default. Only this call raises it; the default stays put for every
# other pass.
DECOMPOSE_READ_TIMEOUT = 600

SYSTEM_PROMPT = """\
You are helping a housing co-op screening committee settle the final set of dimensions its applicant pool varies on.
You are given SEVERAL independent analyses of the SAME pool. They overlap heavily: the same underlying concept is often carved at different granularities, named differently, or split in different places. Your job is to distil them into ONE set of axes that is as FINE as the evidence supports while being mutually NON-OVERLAPPING — collapse re-carvings of a single concept, keep genuinely distinct concepts apart.
Two ways to fail, and the second is worse: keeping redundant near-duplicates (the committee then weights one concept several times over), and merging genuinely different axes into one (the committee loses a distinction it needed, and a lost axis is invisible afterwards). So the bar to MERGE is high; when unsure whether two axes are the same, keep them separate. Two axes that are inverses — opposite poles of one spectrum, so high on one means low on the other — are NOT the same axis; opposite poles mean KEEP, not merge."""

_INSTRUCTIONS = f"""\
## Task
You are given K independent discovery reports for the same applicant pool, in the `<discovery_reports>` block. Produce ONE settled dimension set: the finest collection of axes that each genuinely differentiate this pool and do not overlap each other.

## How to decide, with FALSIFIABLE tests (show the evidence, both ways)
- **To MERGE several input axes into one settled axis:** you must be able to assert they would score the SAME applicant the SAME way AND in the SAME direction — high on one means high on the other. They are the same concept re-carved (reworded, or split by domain but measuring one underlying thing). State that in `decision`. If you cannot make that assertion, they are NOT the same axis — keep them separate.
- **To KEEP two similar-sounding axes apart:** you should be able to point to a plausible applicant who would land HIGH on one and LOW on the other. That is the proof they measure different things. (Illustration, do not borrow the subject: "will you sit on committees" vs. "will you show up for physical work-days" share the word participation, but a person can be eager for one and refuse the other — different axes.)
- **Inverses are NOT duplicates.** If high on one axis always means low on the other (opposite poles of one spectrum), every applicant lands high on one and low on the other — that is the KEEP test met, not the merge test. Keep both as separate axes (the direction-contested case; the committee picks which to score); never fold them as "the same axis, poles reversed" — that buries one orientation and any committee ask on it.
- Same word ≠ same axis, and different words ≠ different axis. Judge by what is measured and its direction, not by labels.
- **Split only where the evidence supports it:** do not manufacture fine distinctions the pool does not actually vary on. Fine is good; fabricated granularity is padding.

## Orientation and direction (carry the discovery rules forward)
- Each settled axis states its poles in `high_end`/`low_end`, carried forward from the source axes — the HIGH end is the more-desirable-fit end (scoring counts higher toward fit). Never write "policy-dependent" or "left to the committee" for an end. If an axis is direction-contested (both ends carry a legitimate fit story and only committee policy decides which is "good"), keep BOTH orientations as separate axes rather than baking in one — the committee chooses later.

## Committee-requested axes (do not lose a human's explicit ask)
- Some input dimensions are flagged `from_committee_request: true`. These were explicitly asked for. You may still merge one INTO a settled axis if it is genuinely the same concept — but then the settled axis MUST carry `from_committee_request: true`, and its `decision` MUST say the request was folded in and into what. NEVER let a committee-requested axis silently disappear.

## Coverage (nothing vanishes silently)
- EVERY input dimension key, across all K reports, must appear in exactly one settled axis's `source_keys`. A redundant carving is MERGED (recorded in source_keys + decision), never dropped. If an axis is genuinely not differentiating, still fold it into its nearest concept and say so — do not silently omit it.

## Output
For each settled axis: `key` (reuse an input key when it's essentially that axis; mint a new snake_case key only for a genuinely merged concept), `name`, `definition` (what it measures, no direction), `high_end` (the more-desirable-fit pole, concrete, never "depends"), `low_end` (the opposite pole), `source_keys` (ALL absorbed input keys), `from_committee_request`, and `decision` (the reasoning — for a merge, the score-alike assertion; for a kept-distinct axis, why).
- `name` is a short committee-facing label — PREFER THE MOST CONCISE name among the merged sources (or one you write).
- Do NOT describe what varies across the applicant pool ("why it differentiates"): you have the reports' definitions, not the pool itself, so any such claim would be unfounded. Report only what you CAN judge from the definitions — identity (`key`/`name`/`definition`) and merge reasoning (`decision`). The pool-grounded "why" is carried forward from the source reports automatically.

## Guardrails
- {INJECTION_GUARD_NOTE}
- Do NOT assign importance or weight — discovering the settled axes is your job; weighting is the committee's, done later. Treat every axis as equally important here.
- Do not score or name individual applicants. Describe the axes."""

# Prompt identity, derived from the static prompt text (folded into the rank-inputs
# fingerprint once wired in Phase 4, like the other rank-chain passes).
PROMPT_VERSION = derive_prompt_version(SYSTEM_PROMPT, _INSTRUCTIONS)


def _reports_block(reports: list[PoolDimensionReport]) -> str:
    """The K discovery reports as a compact JSON list, wrapped in an XML tag. Each
    report keeps its dimensions' key/name/definition + poles + the committee-request
    flag, so the model can judge overlap by definition and carry the poles forward.
    """
    payload = [
        {
            "report_index": i,
            "dimensions": [
                {
                    "key": d.key,
                    "name": d.name,
                    "definition": d.definition,
                    "high_end": d.high_end,
                    "low_end": d.low_end,
                    "from_committee_request": d.from_committee_request,
                }
                for d in report.dimensions
            ],
        }
        for i, report in enumerate(reports)
    ]
    return f"<discovery_reports>\n{json.dumps(payload, indent=2, default=str)}\n</discovery_reports>"


def _kept_block(kept: list[PoolDimension]) -> str:
    """The committee's kept axes, rendered as a prompt section. Empty string when there
    are none, so a first-run (nothing kept yet) prompt is unchanged.

    Kept axes are prior dimensions the committee placed in a working tier. Unlike
    discovery reports (which the model may prune), a kept axis MUST end up in the settled
    set — it is injected here (not seeded into the blind K discoverers) so the settling
    call, which sees every carving at once, can fold any re-discovered twin INTO the kept
    axis (reusing its key so match adopts it and cached scores carry forward) rather than
    emitting a redundant near-duplicate.
    """
    if not kept:
        return ""
    payload = [
        {"key": d.key, "name": d.name, "definition": d.definition}
        for d in kept
    ]
    return f"""\

## Committee-kept axes (MUST survive)
The `<kept_axes>` block lists axes the committee explicitly kept from a prior run (by tiering them). EACH one MUST appear in your settled set — reuse its exact `key`. Leave `from_committee_request` FALSE on it: that flag marks only a fresh proposal a member asked for THIS run, and a kept axis is an ordinary carried dimension. If a discovery report re-surfaced the same concept under a different key, FOLD that discovered axis into the kept axis (list both in `source_keys`, keep the kept axis's key) rather than emitting two. A kept axis is never dropped, even if no discovery report named it — carry it through on its own.

<kept_axes>
{json.dumps(payload, indent=2, default=str)}
</kept_axes>
"""


def build_prompt(
    reports: list[PoolDimensionReport],
    kept: list[PoolDimension] | None = None,
) -> str:
    return f"{_INSTRUCTIONS}{_kept_block(kept or [])}\n\n{_reports_block(reports)}"


# --- Cost estimation (non-prompt) ---

# The input scales with K × dimensions (all K reports in the prompt); output scales
# with the settled set (~30 axes, each with definition + source_keys + decision
# reasoning, but no per-axis why — that's carried forward from the source). Calibrated
# to observed spend (~5600 output tokens); re-calibrate against the ledger if the
# decompose prompt's output shape changes.
_DECOMPOSE_OUTPUT_TOKENS = 5600


def estimate_decompose(reports: list[PoolDimensionReport], settings: AppSettings) -> float:
    """Projected cost of the one decomposition call. ~200 tokens per input dimension
    across all K reports (key + name + definition), plus the settled-set output.
    """
    input_dims = sum(len(r.dimensions) for r in reports)
    usage = Usage(
        input_tokens=200 * max(input_dims, 1),
        output_tokens=_DECOMPOSE_OUTPUT_TOKENS,
    )
    return cost_usd(settings.ai.decompose_model, usage)


def to_pool_report(
    decomposition: DecompositionReport,
    input_reports: list[PoolDimensionReport] | None = None,
    kept: list[PoolDimension] | None = None,
) -> PoolDimensionReport:
    """Project the settled ``DecompositionReport`` onto a ``PoolDimensionReport`` — the
    shape the rest of the rank chain (match pass, scoring, storage) already speaks. The
    decomposition-only fields (``source_keys``, ``decision``) are dropped here; they are
    preserved separately in the decompose audit (see ``decompose_audit_payload``). The
    ``from_committee_request`` flag rides through, since it drives the D9
    committee-request protection downstream.

    ``why_it_differentiates`` is NOT taken from the decomposition (it doesn't produce
    one — see ``DecomposedDimension``). Instead it is carried forward from the PRIMARY
    source axis: the discoverer that coined this axis read the pool, so its ``why`` is
    the real, essay-grounded one. The primary source is the first ``source_key`` that
    resolves to an input dimension (or an injected ``kept`` axis, which carries its own
    prior pool-grounded ``why``). Falls back to an empty string only if no source key
    resolves — which shouldn't happen once kept axes are included, since every settled
    axis's sources are drawn from the reports or the kept axes.
    """
    why_by_key: dict[str, str] = {}
    for report in input_reports or []:
        for dim in report.dimensions:
            # First writer wins — a key repeated across K reports keeps report 0's why.
            why_by_key.setdefault(dim.key, dim.why_it_differentiates)
    for kept_dim in kept or []:
        why_by_key.setdefault(kept_dim.key, kept_dim.why_it_differentiates)

    def _carried_why(d: DecomposedDimension) -> str:
        for sk in d.source_keys:
            if sk in why_by_key:
                return why_by_key[sk]
        return ""

    return PoolDimensionReport(
        dimensions=[
            PoolDimension(
                key=d.key,
                name=d.name,
                definition=d.definition,
                high_end=d.high_end,
                low_end=d.low_end,
                why_it_differentiates=_carried_why(d),
                from_committee_request=d.from_committee_request,
            )
            for d in decomposition.dimensions
        ],
    )


def enforce_committee_requests(
    decomposition: DecompositionReport,
    input_reports: list[PoolDimensionReport],
    kept: list[PoolDimension] | None = None,
) -> tuple[DecompositionReport, list[dict]]:
    """D9 guard (SPEC "Fan-Out Redesign", D9): a committee ask must never be silently
    merged away. Deterministic backstop for the prompt instruction — prompts guide, they
    don't guarantee.

    Two sources of "committee ask" are guarded — both get the same never-vanish
    guarantee, but they mean DIFFERENT things for the ``from_committee_request`` flag:
      - **Proposals**, which entered via a discovery report and are marked
        ``from_committee_request`` on their input dimension. This flag is THIS run's
        provenance — "a member asked for this axis on this run" — and it drives the
        audit badge + D9 trail. It must be authoritative: true iff a fresh proposal was
        absorbed, so it clears on the next run (when the proposal is gone).
      - **Kept axes** (``kept``), prior dimensions injected at decomposition (NOT into
        discovery) because the committee tiered them. They are never in ``input_reports``,
        so they are folded into the survive set here by their own key. A kept axis is an
        ordinary carried dimension: it must never vanish, but it carries NO request flag
        (the committee tiered it on some prior run; that isn't a fresh ask this run).

    Failure modes repaired here, computed from the survive set vs. what decomposition
    returned:
      - **Flag drift:** the flag on each settled axis is recomputed from scratch — true
        iff it absorbed a proposal source key, false otherwise — so neither a model that
        dropped it on a merge nor one that stamped it on a kept/plain axis can make it lie.
      - **Silent drop:** an asked-for key (proposal OR kept) appears in NO settled axis's
        ``source_keys`` — decomposition dropped it. We re-add it as its own settled axis
        (restoring the input/kept text), flagged only if it was a proposal.

    Returns the corrected report and a ``folded`` list — the asked-for axes merged INTO
    another axis (not kept standalone), each ``{request_key, into_key}`` — so the caller
    can surface "your proposal/kept axis X was folded into Y" (never a silent
    disappearance). An axis kept under its own key is not "folded" and isn't listed.
    """
    # Proposals (flagged in the reports) carry the request flag; kept axes (injected
    # separately) get the survival guarantee only. Both share the never-vanish repair.
    proposed = {
        d.key: d
        for r in input_reports
        for d in r.dimensions
        if d.from_committee_request
    }
    survive = dict(proposed)  # everything that must not vanish, keyed by dimension key
    for kept_dim in kept or []:
        survive.setdefault(kept_dim.key, kept_dim)
    if not survive:
        # No asks at all — but still make the flag authoritative: strip any the model
        # stamped on its own (nothing was proposed this run, so nothing may claim it).
        dims = [
            d.model_copy(update={"from_committee_request": False})
            if d.from_committee_request
            else d
            for d in decomposition.dimensions
        ]
        return decomposition.model_copy(update={"dimensions": dims}), []

    dims = [d.model_copy() for d in decomposition.dimensions]
    covered: dict[str, str] = {}  # asked-for input key -> settled axis key that absorbed it
    for settled in dims:
        absorbed_proposal = any(sk in proposed for sk in settled.source_keys)
        for sk in settled.source_keys:
            if sk in survive:
                covered[sk] = settled.key
        # Flag is authoritative: true iff this axis absorbed a fresh proposal, false
        # otherwise — so a kept axis reads as an ordinary dimension and the flag clears
        # next run when the proposal is gone.
        settled.from_committee_request = absorbed_proposal

    folded: list[dict] = []
    for ask_key, ask_dim in survive.items():
        settled_key = covered.get(ask_key)
        if settled_key is None:
            # Silent drop: re-add the asked-for axis as its own settled dimension. Flag it
            # only if it was a fresh proposal (kept axes re-add as plain dimensions).
            dims.append(
                DecomposedDimension(
                    key=ask_dim.key,
                    name=ask_dim.name,
                    definition=ask_dim.definition,
                    high_end=ask_dim.high_end,
                    low_end=ask_dim.low_end,
                    source_keys=[ask_dim.key],
                    from_committee_request=ask_key in proposed,
                    decision="Re-added by the D9 guard — decomposition dropped this committee-asked axis.",
                )
            )
        elif settled_key != ask_key:
            # Merged INTO another axis (not kept standalone) — surface it, don't undo it.
            folded.append({"request_key": ask_key, "into_key": settled_key})

    return decomposition.model_copy(update={"dimensions": dims}), folded


def decompose_audit_payload(
    decomposition: DecompositionReport,
    input_reports: list[PoolDimensionReport],
    narrative: str | None = None,
    folded_requests: list[dict] | None = None,
) -> dict:
    """Shape the decomposition for storage on the run (mirrors ``reconcile_audit``).

    Captures, per settled axis, the ``source_keys`` it absorbed and the ``decision``
    reasoning (why merged / kept distinct) — the merge audit trail, and the surface the
    Insights panel renders (the reconcile-reasoning lesson: persist the *why*). Also the
    input dimension count (K reports → how many raw axes fed in) so the settle-down
    ratio is inspectable. A merge is any settled axis with more than one source key.
    """
    settled = decomposition.dimensions
    return {
        "input_report_count": len(input_reports),
        "input_dimension_count": sum(len(r.dimensions) for r in input_reports),
        "settled_count": len(settled),
        "merge_count": sum(1 for d in settled if len(d.source_keys) > 1),
        "settled": [
            {
                "key": d.key,
                "name": d.name,
                "source_keys": d.source_keys,
                "from_committee_request": d.from_committee_request,
                "decision": d.decision,
            }
            for d in settled
        ],
        # D9: committee-requested axes that decomposition folded INTO another axis
        # (request_key → into_key). The UI surfaces "your proposal X was folded into Y"
        # so a fold is visible, never silent. Empty when no request was merged away.
        "folded_requests": folded_requests or [],
        "narrative": narrative,
    }


def decompose_dimensions(
    provider: AIProvider,
    *,
    reports: list[PoolDimensionReport],
    settings: AppSettings,
    kept: list[PoolDimension] | None = None,
    on_delta: DeltaSink | None = None,
) -> tuple[DecompositionReport, str | None, PassCost]:
    """Single-call baseline: settle the K reports into one finest-non-overlapping set.

    ``kept`` are prior dimensions the committee kept (by tiering them); they are injected
    into the prompt so the settling call folds any re-discovered twin into them (reusing
    keys) and keeps them present regardless (the ``enforce_committee_requests`` backstop
    guarantees it deterministically). Returns ``(report, narrative, cost_usd)``. Runs on
    the discovery (synthesis) model — the same hard judgment discovery makes, across
    reports. With fewer than 2 reports there is nothing to settle; the sole report's
    dimensions are returned wrapped as a trivial decomposition (kept axes are folded in by
    the backstop downstream) at no cost.
    """
    if len(reports) < 2:
        only = reports[0] if reports else PoolDimensionReport(dimensions=[])
        trivial = DecompositionReport(
            dimensions=[
                DecomposedDimension(
                    key=d.key,
                    name=d.name,
                    definition=d.definition,
                    high_end=d.high_end,
                    low_end=d.low_end,
                    source_keys=[d.key],
                    from_committee_request=d.from_committee_request,
                    decision="Single discovery report — no decomposition needed.",
                )
                for d in only.dimensions
            ],
        )
        return trivial, None, PassCost()

    result = provider.structured_output(
        model_id=settings.ai.decompose_model,
        schema=DecompositionReport,
        prompt=build_prompt(reports, kept),
        system_prompt=SYSTEM_PROMPT,
        on_delta=on_delta,
        read_timeout=DECOMPOSE_READ_TIMEOUT,
    )
    return result.output, result.narrative, PassCost.from_usage(result.model_id, result.usage)
