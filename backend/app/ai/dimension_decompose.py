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

This single structured call is the decomposition step, wired into ``rank_run``. It won
a bake-off against a multi-agent splitter↔merger loop (the loop was costlier, no more
stable, and worse on overlaps — see the fan-out redesign notes); the loop is not built.
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
For each settled axis: `key` (reuse an input key when it's essentially that axis; mint a new snake_case key only for a genuinely merged concept), `name`, `definition` (what it measures + which end is high), `source_keys` (ALL absorbed input keys), `from_committee_request`, and `decision` (the reasoning — for a merge, the score-alike assertion; for a kept-distinct axis, why). Also a 2-4 sentence neutral `summary`.
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


def _favourites_block(favourites: list[PoolDimension]) -> str:
    """The committee's favourited axes, rendered as a prompt section. Empty string
    when there are none, so an un-favourited run's prompt is unchanged.

    Favourites are prior dimensions the committee chose to keep. Unlike discovery
    reports (which the model may prune), a favourite MUST end up in the settled set —
    it is injected here (not seeded into the blind K discoverers) so the settling call,
    which sees every carving at once, can fold any re-discovered twin INTO the
    favourite (reusing its key so match adopts it and cached scores carry forward)
    rather than emitting a redundant near-duplicate.
    """
    if not favourites:
        return ""
    payload = [
        {"key": d.key, "name": d.name, "definition": d.definition}
        for d in favourites
    ]
    return f"""\

## Committee favourites (MUST survive)
The `<favourite_axes>` block lists axes the committee explicitly kept from a prior run. EACH one MUST appear in your settled set — reuse its exact `key`, and set `from_committee_request: true` on it. If a discovery report re-surfaced the same concept under a different key, FOLD that discovered axis into the favourite (list both in `source_keys`, keep the favourite's key) rather than emitting two. A favourite is never dropped, even if no discovery report named it — carry it through on its own.

<favourite_axes>
{json.dumps(payload, indent=2, default=str)}
</favourite_axes>
"""


def build_prompt(
    reports: list[PoolDimensionReport],
    favourites: list[PoolDimension] | None = None,
) -> str:
    return f"{_INSTRUCTIONS}{_favourites_block(favourites or [])}\n\n{_reports_block(reports)}"


# --- Cost estimation (non-prompt) ---

# The input scales with K × dimensions (all K reports in the prompt); output scales
# with the settled set (~30 axes, each with definition + source_keys + decision
# reasoning). Calibrated to observed spend (2026-07-11): the real settled output ran
# ~8000 tokens; dropping the per-axis why_it_differentiates (~30 × ~80 tok, now carried
# forward from the source instead of generated here) trims ~2400 → ~5600. Re-calibrate
# against the ledger after a real run on the trimmed prompt.
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
    favourites: list[PoolDimension] | None = None,
) -> PoolDimensionReport:
    """Project the settled ``DecompositionReport`` onto a ``PoolDimensionReport`` — the
    shape the rest of the rank chain (match pass, scoring, storage) already speaks. The
    decomposition-only fields (``source_keys``, ``decision``) are dropped here; they are
    preserved separately in the decompose audit (see ``decompose_audit_payload``). The
    ``from_committee_request`` flag rides through, since it drives auto-favouriting and
    the D9 committee-request protection downstream.

    ``why_it_differentiates`` is NOT taken from the decomposition (it doesn't produce
    one — see ``DecomposedDimension``). Instead it is carried forward from the PRIMARY
    source axis: the discoverer that coined this axis read the pool, so its ``why`` is
    the real, essay-grounded one. The primary source is the first ``source_key`` that
    resolves to an input dimension (or an injected ``favourite``, which carries its own
    prior pool-grounded ``why``). Falls back to an empty string only if no source key
    resolves — which shouldn't happen once favourites are included, since every settled
    axis's sources are drawn from the reports or the favourites.
    """
    why_by_key: dict[str, str] = {}
    for report in input_reports or []:
        for dim in report.dimensions:
            # First writer wins — a key repeated across K reports keeps report 0's why.
            why_by_key.setdefault(dim.key, dim.why_it_differentiates)
    for fav in favourites or []:
        why_by_key.setdefault(fav.key, fav.why_it_differentiates)

    def _carried_why(d: DecomposedDimension) -> str:
        for sk in d.source_keys:
            if sk in why_by_key:
                return why_by_key[sk]
        return ""

    return PoolDimensionReport(
        summary=decomposition.summary,
        dimensions=[
            PoolDimension(
                key=d.key,
                name=d.name,
                definition=d.definition,
                why_it_differentiates=_carried_why(d),
                from_committee_request=d.from_committee_request,
            )
            for d in decomposition.dimensions
        ],
    )


def enforce_committee_requests(
    decomposition: DecompositionReport,
    input_reports: list[PoolDimensionReport],
    favourites: list[PoolDimension] | None = None,
) -> tuple[DecompositionReport, list[dict]]:
    """D9 guard (SPEC "Fan-Out Redesign", D9): a committee ask must never be silently
    merged away. Deterministic backstop for the prompt instruction — prompts guide, they
    don't guarantee.

    Two sources of "committee ask" are guarded, identically:
      - **Proposals**, which entered via a discovery report and are marked
        ``from_committee_request`` on their input dimension.
      - **Favourites** (``favourites``), prior dimensions injected at decomposition (NOT
        into discovery). They are never in ``input_reports``, so they are folded into the
        ask set here by their own key — a favourite is an even harder guarantee than a
        proposal (the committee already chose it), so the same "never vanish" repair
        applies.

    Three failure modes repaired here, computed from the ask set vs. what decomposition
    returned:
      - **Flag loss on merge:** an asked-for key was absorbed into a settled axis, but
        that axis came back ``from_committee_request: false`` — the provenance that drives
        auto-favouriting and the UI badge. We force the flag back true.
      - **Silent drop:** an asked-for key appears in NO settled axis's ``source_keys`` —
        decomposition dropped it. We re-add it as its own settled axis (restoring the
        input/favourite text) so it cannot vanish.

    Returns the corrected report and a ``folded`` list — the asked-for axes merged INTO
    another axis (not kept standalone), each ``{request_key, into_key}`` — so the caller
    can surface "your proposal/favourite X was folded into Y" (never a silent
    disappearance). An axis kept under its own key is not "folded" and isn't listed.
    """
    # Both proposals (flagged in the reports) and favourites (injected separately) are
    # committee asks with the same never-vanish guarantee, keyed by their dimension key.
    requested = {
        d.key: d
        for r in input_reports
        for d in r.dimensions
        if d.from_committee_request
    }
    for fav in favourites or []:
        requested.setdefault(fav.key, fav)
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
    favourites: list[PoolDimension] | None = None,
    on_delta: DeltaSink | None = None,
) -> tuple[DecompositionReport, str | None, float]:
    """Single-call baseline: settle the K reports into one finest-non-overlapping set.

    ``favourites`` are prior dimensions the committee kept; they are injected into the
    prompt so the settling call folds any re-discovered twin into them (reusing keys) and
    keeps them present regardless (the ``enforce_committee_requests`` backstop guarantees
    it deterministically). Returns ``(report, narrative, cost_usd)``. Runs on the
    discovery (synthesis) model — the same hard judgment discovery makes, across reports.
    With fewer than 2 reports there is nothing to settle; the sole report's dimensions are
    returned wrapped as a trivial decomposition (favourites are folded in by the backstop
    downstream) at no cost.
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
                    source_keys=[d.key],
                    from_committee_request=d.from_committee_request,
                    decision="Single discovery report — no decomposition needed.",
                )
                for d in only.dimensions
            ],
        )
        return trivial, None, 0.0

    result = provider.structured_output(
        model_id=settings.ai.decompose_model,
        schema=DecompositionReport,
        prompt=build_prompt(reports, favourites),
        system_prompt=SYSTEM_PROMPT,
        on_delta=on_delta,
        read_timeout=DECOMPOSE_READ_TIMEOUT,
    )
    return result.output, result.narrative, cost_usd(result.model_id, result.usage)
