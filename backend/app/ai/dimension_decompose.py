"""Dimension decomposition: distil K parallel discovery reports into the finest set
of axes that are each genuinely differentiating AND mutually non-overlapping
(SPEC "Fan-Out Redesign", Phase 3 — the single-call baseline variant).

K fresh-context discovery calls carve the same pool at different, overlapping
granularities (the diversity Phase 2 produces). This step sees all K at once — the
thing the sequential chain never could — and settles ONE non-overlapping set. The
question it can now answer that the old reconcile pass could not: "is this axis
redundant with one we already have?" (decidable with all carvings visible), instead
of "does the pool vary on this?" (structurally unfalsifiable — discovery only ever
coined an axis because it saw variance; see the convergence case study).

The failure is two-sided and the prompt must guard both:
  - UNDER-merge: keep nine "participation" re-carvings → the committee unknowingly
    weights one concept 9×.
  - OVER-merge: collapse a nurse's health-safety into a treasurer's finance → the
    committee loses a lever it needed. This is the higher-stakes error (a lost axis
    is invisible downstream), so the bar to MERGE is high, not the bar to split.

The two forces are given falsifiable tests, mirroring the discovery one-concept rule
and the match pass's identity bar: to MERGE two axes you must assert they'd score the
same applicant the same way; to KEEP two apart you must be able to name an applicant
high on one and low on the other. Committee-requested axes get extra protection (D9):
never merged away silently — the flag rides through and the decision must say so.

This is the BASELINE contender in the Phase 3 bake-off (one structured call). The
multi-agent splitter↔merger↔decider loop is the other; the Phase-1 overlap judge
picks the winner on finest + stable. Not yet wired into ``rank_run`` — that is
Phase 4, after the bake-off names a winner.
"""

from __future__ import annotations

import json

from app.ai.analysis import derive_prompt_version
from app.ai.pricing import cost_usd
from app.ai.prompt_fragments import INJECTION_GUARD_NOTE
from app.ai.provider import AIProvider, DeltaSink, Usage
from app.ai.schemas import (
    DecomposedDimension,
    DecompositionReport,
    OverMergeReport,
    PoolDimension,
    PoolDimensionReport,
)
from app.schemas.settings import AppSettings

KIND = "dimension_decompose"  # for logging / the debug view; not a cached per-app kind

# Bedrock read timeout (s) for the decomposition call specifically. It streams a large
# reasoned set (settle ~250 input dims → ~28 axes, each with merge reasoning) and blows
# the provider's 120s default — confirmed twice (over-gen experiment + the bake-off).
# Only this call raises it; the default stays put for every other pass.
DECOMPOSE_READ_TIMEOUT = 600

SYSTEM_PROMPT = """\
You are helping a housing co-op screening committee settle the final set of dimensions its applicant pool varies on.
You are given SEVERAL independent analyses of the SAME pool. They overlap heavily: the same underlying concept is often carved at different granularities, named differently, or split in different places. Your job is to distil them into ONE set of axes that is as FINE as the evidence supports while being mutually NON-OVERLAPPING — collapse re-carvings of a single concept, keep genuinely distinct concepts apart.
Two ways to fail, and the second is worse: keeping redundant near-duplicates (the committee then weights one concept several times over), and merging genuinely different axes into one (the committee loses a distinction it needed, and a lost axis is invisible afterwards). So the bar to MERGE is high; when unsure whether two axes are the same, keep them separate."""

_INSTRUCTIONS = f"""\
## Task
You are given K independent discovery reports for the same applicant pool, in the `<discovery_reports>` block. Produce ONE settled dimension set: the finest collection of axes that each genuinely differentiate this pool and do not overlap each other.

## How to decide, with FALSIFIABLE tests (show the evidence, both ways)
- **To MERGE several input axes into one settled axis:** you must be able to assert they would score the SAME applicant essentially the SAME way — they are the same concept re-carved (reworded, or split by domain but measuring one underlying thing). State that in `decision`. If you cannot make that assertion, they are NOT the same axis — keep them separate.
- **To KEEP two similar-sounding axes apart:** you should be able to point to a plausible applicant who would land HIGH on one and LOW on the other. That is the proof they measure different things. (Illustration, do not borrow the subject: "will you sit on committees" vs. "will you show up for physical work-days" share the word participation, but a person can be eager for one and refuse the other — different axes.)
- Same word ≠ same axis, and different words ≠ different axis. Judge by what is measured, not by labels.
- **Split only where the evidence supports it:** do not manufacture fine distinctions the pool does not actually vary on. Fine is good; fabricated granularity is padding.

## Orientation and direction (carry the discovery rules forward)
- Orient each settled axis so the HIGH end is the more-desirable-fit end (scoring counts higher toward fit). If an axis is direction-contested (both ends carry a legitimate fit story and only committee policy decides which is "good"), keep BOTH orientations as separate axes rather than baking in one — the committee chooses later.

## Committee-requested axes (do not lose a human's explicit ask)
- Some input dimensions are flagged `from_committee_request: true`. These were explicitly asked for. You may still merge one INTO a settled axis if it is genuinely the same concept — but then the settled axis MUST carry `from_committee_request: true`, and its `decision` MUST say the request was folded in and into what. NEVER let a committee-requested axis silently disappear.

## Coverage (nothing vanishes silently)
- EVERY input dimension key, across all K reports, must appear in exactly one settled axis's `source_keys`. A redundant carving is MERGED (recorded in source_keys + decision), never dropped. If an axis is genuinely not differentiating, still fold it into its nearest concept and say so — do not silently omit it.

## Output
For each settled axis: `key` (reuse an input key when it's essentially that axis; mint a new snake_case key only for a genuinely merged concept), `name`, `definition` (what it measures + which end is high), `why_it_differentiates`, `source_keys` (ALL absorbed input keys), `from_committee_request`, and `decision` (the reasoning — for a merge, the score-alike assertion; for a kept-distinct axis, why). Also a 2-4 sentence neutral `summary`.

## Guardrails
- {INJECTION_GUARD_NOTE}
- Do NOT assign importance or weight — discovering the settled axes is your job; weighting is the committee's, done later. Treat every axis as equally important here.
- Do not score or name individual applicants. Describe the axes."""

# Prompt identity, derived from the static prompt text (folded into the rank-inputs
# fingerprint once wired in Phase 4, like the other rank-chain passes).
PROMPT_VERSION = derive_prompt_version(SYSTEM_PROMPT, _INSTRUCTIONS)


def _reports_block(reports: list[PoolDimensionReport]) -> str:
    """The K discovery reports as a compact JSON list, wrapped in an XML tag. Each
    report keeps its dimensions' key/name/definition + the committee-request flag, so
    the model can judge overlap by definition and protect requested axes.
    """
    payload = [
        {
            "report_index": i,
            "dimensions": [
                {
                    "key": d.key,
                    "name": d.name,
                    "definition": d.definition,
                    "from_committee_request": d.from_committee_request,
                }
                for d in report.dimensions
            ],
        }
        for i, report in enumerate(reports)
    ]
    return f"<discovery_reports>\n{json.dumps(payload, indent=2, default=str)}\n</discovery_reports>"


def build_prompt(reports: list[PoolDimensionReport]) -> str:
    return f"{_INSTRUCTIONS}\n\n{_reports_block(reports)}"


# --- Cost estimation (non-prompt) ---

# The input scales with K × dimensions (all K reports in the prompt); output scales
# with the settled set (~30 axes, each with definition + source_keys + decision
# reasoning). Calibrated to observed spend (2026-07-11): the real settled output runs
# ~8000 tokens — was 4000, which under-estimated decomposition ~2x.
_DECOMPOSE_OUTPUT_TOKENS = 8000


def estimate_decompose(reports: list[PoolDimensionReport], settings: AppSettings) -> float:
    """Projected cost of the one decomposition call. ~200 tokens per input dimension
    across all K reports (key + name + definition), plus the settled-set output.
    """
    input_dims = sum(len(r.dimensions) for r in reports)
    usage = Usage(
        input_tokens=200 * max(input_dims, 1),
        output_tokens=_DECOMPOSE_OUTPUT_TOKENS,
    )
    return cost_usd(settings.ai.discovery_model, usage)


def to_pool_report(decomposition: DecompositionReport) -> PoolDimensionReport:
    """Project the settled ``DecompositionReport`` onto a ``PoolDimensionReport`` — the
    shape the rest of the rank chain (match pass, scoring, storage) already speaks. The
    decomposition-only fields (``source_keys``, ``decision``) are dropped here; they are
    preserved separately in the decompose audit (see ``decompose_audit_payload``). The
    ``from_committee_request`` flag rides through, since it drives auto-favouriting and
    the D9 committee-request protection downstream.
    """
    return PoolDimensionReport(
        summary=decomposition.summary,
        dimensions=[
            PoolDimension(
                key=d.key,
                name=d.name,
                definition=d.definition,
                why_it_differentiates=d.why_it_differentiates,
                from_committee_request=d.from_committee_request,
            )
            for d in decomposition.dimensions
        ],
    )


def enforce_committee_requests(
    decomposition: DecompositionReport,
    input_reports: list[PoolDimensionReport],
) -> tuple[DecompositionReport, list[dict]]:
    """D9 guard (SPEC "Fan-Out Redesign", D9): a committee-requested axis must never be
    silently merged away. Deterministic backstop for the prompt instruction — prompts
    guide, they don't guarantee.

    Two failure modes repaired here, both computed from the input `from_committee_request`
    flags vs. what decomposition returned:
      - **Flag loss on merge:** a requested input key was absorbed into a settled axis,
        but that axis came back ``from_committee_request: false`` — the provenance that
        drives auto-favouriting and the UI badge. We force the flag back true.
      - **Silent drop:** a requested input key appears in NO settled axis's
        ``source_keys`` — decomposition dropped it entirely. We re-add it as its own
        settled axis (restoring the input's text) so it cannot vanish.

    Returns the corrected report and a ``folded`` list — the requested axes that were
    merged INTO another axis (not kept standalone), each ``{request_key, into_key}`` —
    so the caller can surface "your proposal X was folded into Y" to the committee
    (never a silent disappearance). A requested axis kept as its own settled axis is not
    "folded" and isn't listed.
    """
    requested = {
        d.key: d
        for r in input_reports
        for d in r.dimensions
        if d.from_committee_request
    }
    if not requested:
        return decomposition, []

    dims = [d.model_copy() for d in decomposition.dimensions]
    covered: dict[str, str] = {}  # requested input key -> settled axis key that absorbed it
    for settled in dims:
        for sk in settled.source_keys:
            if sk in requested:
                covered[sk] = settled.key
                # Flag-loss repair: a settled axis absorbing a request carries the flag.
                if not settled.from_committee_request:
                    settled.from_committee_request = True

    folded: list[dict] = []
    for req_key, req_dim in requested.items():
        settled_key = covered.get(req_key)
        if settled_key is None:
            # Silent drop: re-add the requested axis as its own settled dimension.
            dims.append(
                DecomposedDimension(
                    key=req_dim.key,
                    name=req_dim.name,
                    definition=req_dim.definition,
                    why_it_differentiates=req_dim.why_it_differentiates,
                    source_keys=[req_dim.key],
                    from_committee_request=True,
                    decision="Re-added by the D9 guard — decomposition dropped this committee-requested axis.",
                )
            )
        elif settled_key != req_key:
            # Merged INTO another axis (not kept standalone) — surface it, don't undo it.
            folded.append({"request_key": req_key, "into_key": settled_key})

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
    on_delta: DeltaSink | None = None,
) -> tuple[DecompositionReport, str | None, float]:
    """Single-call baseline: settle the K reports into one finest-non-overlapping set.

    Returns ``(report, narrative, cost_usd)``. Runs on the discovery (synthesis) model
    — this is the same hard judgment discovery makes, applied across reports. With fewer
    than 2 reports there is nothing to reconcile; the sole report's dimensions are
    returned wrapped as a trivial decomposition (each its own source key) at no cost.
    """
    if len(reports) < 2:
        only = reports[0] if reports else PoolDimensionReport(summary="", dimensions=[])
        trivial = DecompositionReport(
            summary=only.summary,
            dimensions=[
                DecomposedDimension(
                    key=d.key,
                    name=d.name,
                    definition=d.definition,
                    why_it_differentiates=d.why_it_differentiates,
                    source_keys=[d.key],
                    from_committee_request=d.from_committee_request,
                    decision="Single discovery report — no decomposition needed.",
                )
                for d in only.dimensions
            ],
        )
        return trivial, None, 0.0

    result = provider.structured_output(
        model_id=settings.ai.discovery_model,
        schema=DecompositionReport,
        prompt=build_prompt(reports),
        system_prompt=SYSTEM_PROMPT,
        on_delta=on_delta,
        read_timeout=DECOMPOSE_READ_TIMEOUT,
    )
    return result.output, result.narrative, cost_usd(result.model_id, result.usage)


# --- Multi-agent variant: bounded merger ↔ splitter loop (D7) ----------------
#
# The other bake-off contender. Round 1 is the baseline (a merge-biased Merger).
# Then a Splitter adversarially challenges each merge, and any merge it overturns —
# by naming an applicant high on one absorbed axis and low on another — is split back
# into its sources. Bounded (hard round cap) and MONOTONIC (a round only ever splits,
# never re-merges), so it converges: it stops when a round overturns nothing, or at the
# cap. The point is to test whether the adversarial split-back catches over-merges the
# single call makes — the exact failure the Phase-1 judge showed is the higher-stakes
# one. If it rarely overturns, the baseline is good enough and the loop is ceremony.

SPLITTER_SYSTEM_PROMPT = """\
You are a skeptical reviewer on a housing co-op screening committee, checking whether a set of "merged" dimensions collapsed axes that should have stayed separate.
Each merged axis fused several source axes on the claim they measure the same thing. Your job is the opposite pressure: find the merges that are WRONG — where a plausible applicant would score HIGH on one fused source and LOW on another, proving they are different axes the committee would want to weight separately.
Overturn a merge ONLY when you can name that applicant or profile. A merge you cannot break stands — do not overturn one just because the sources were worded differently or feel broad. Being asked "is this over-merged?" is not evidence that it is."""

_SPLITTER_INSTRUCTIONS = f"""\
## Task
You are given a set of MERGED dimensions in `<merged_dimensions>`. Each lists the source axes it fused (`source_keys`) and the reasoning for the merge. For each, judge: did this merge collapse genuinely-distinct axes?

## The falsifiable test (the only way to overturn a merge)
Name an applicant or applicant profile who would land HIGH on one fused source and LOW on another. If you can, the merge is wrong (`overmerged: true`) — say who and which sources split apart. If you cannot, the merge stands (`overmerged: false`) — one sentence on why they really are one axis.
- Default to NOT overturning. The merge was made by a careful pass; overturn only with concrete splitting evidence, not a hunch that an axis "feels broad".
- Different WORDING is not a reason to split — only different MEASUREMENT (an applicant who ranks differently on the two) is.

## Output
One challenge per merged axis you were shown: its `key`, `overmerged`, and `splitting_evidence` (the naming, or why it holds).

## Guardrails
- {INJECTION_GUARD_NOTE}
- Do not invent applicants not consistent with a real co-op pool; the splitting profile must be plausible."""

SPLITTER_PROMPT_VERSION = derive_prompt_version(
    SPLITTER_SYSTEM_PROMPT, _SPLITTER_INSTRUCTIONS
)


def _merged_block(report: DecompositionReport) -> str:
    """The decomposition's MERGED axes (more than one source key) as JSON for the
    Splitter. Kept-as-is axes are omitted — there is nothing to split.
    """
    merges = [
        {
            "key": d.key,
            "definition": d.definition,
            "source_keys": d.source_keys,
            "merge_reasoning": d.decision,
        }
        for d in report.dimensions
        if len(d.source_keys) > 1
    ]
    return f"<merged_dimensions>\n{json.dumps(merges, indent=2, default=str)}\n</merged_dimensions>"


def _split_back(
    report: DecompositionReport,
    overturned_keys: set[str],
    sources_by_key: dict[str, PoolDimension],
) -> DecompositionReport:
    """Split each overturned merged axis back into one settled axis per source key,
    restoring each source's original text. Non-overturned axes pass through unchanged.
    """
    dims: list[DecomposedDimension] = []
    for d in report.dimensions:
        if d.key in overturned_keys and len(d.source_keys) > 1:
            for sk in d.source_keys:
                src = sources_by_key.get(sk)
                dims.append(
                    DecomposedDimension(
                        key=sk,
                        name=src.name if src else sk,
                        definition=src.definition if src else d.definition,
                        why_it_differentiates=(
                            src.why_it_differentiates if src else d.why_it_differentiates
                        ),
                        source_keys=[sk],
                        from_committee_request=(
                            src.from_committee_request if src else d.from_committee_request
                        ),
                        decision=f"Split back out of '{d.key}' — the splitter judged that merge over-merged.",
                    )
                )
        else:
            dims.append(d)
    return report.model_copy(update={"dimensions": dims})


def decompose_dimensions_loop(
    provider: AIProvider,
    *,
    reports: list[PoolDimensionReport],
    settings: AppSettings,
    max_rounds: int = 2,
) -> tuple[DecompositionReport, list[dict], float]:
    """Bounded merger↔splitter loop (D7 multi-agent variant). Round 1 is the baseline
    decomposition; each subsequent round runs the Splitter over the current merges and
    splits back any it overturns, until a round overturns nothing or ``max_rounds`` is
    hit. Returns ``(report, round_audit, cost_usd)``; ``round_audit`` records each
    Splitter ballot for inspection (the reconcile-audit lesson: persist the reasoning).
    """
    report, _narr, cost = decompose_dimensions(
        provider, reports=reports, settings=settings
    )
    total_cost = cost
    # Original source dimensions, by key, so split-back can restore their text.
    sources_by_key = {d.key: d for r in reports for d in r.dimensions}

    round_audit: list[dict] = []
    for _round in range(max_rounds):
        merges = [d for d in report.dimensions if len(d.source_keys) > 1]
        if not merges:
            break  # nothing merged → nothing to challenge
        result = provider.structured_output(
            model_id=settings.ai.discovery_model,
            schema=OverMergeReport,
            prompt=f"{_SPLITTER_INSTRUCTIONS}\n\n{_merged_block(report)}",
            system_prompt=SPLITTER_SYSTEM_PROMPT,
        )
        total_cost += cost_usd(result.model_id, result.usage)
        ballot: OverMergeReport = result.output
        merge_keys = {d.key for d in merges}
        overturned = {
            c.key for c in ballot.challenges if c.overmerged and c.key in merge_keys
        }
        round_audit.append(
            {
                "challenges": [
                    {"key": c.key, "overmerged": c.overmerged, "evidence": c.splitting_evidence}
                    for c in ballot.challenges
                ],
                "overturned": sorted(overturned),
            }
        )
        if not overturned:
            break  # the splitter accepted every merge → converged
        report = _split_back(report, overturned, sources_by_key)

    return report, round_audit, total_cost
