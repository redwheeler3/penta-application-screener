"""Dimension identity matching: map a freshly-discovered dimension set onto the
prior run's, so tier placements and cached scores carry forward across a re-rank
(SPEC "Tier Carry-Forward On Re-Rank").

Discovery re-discovers dimensions *blind*; this pass then answers a narrow identity
question: which new dimension is the same concept as which old one? It recognizes
sameness, never weighs importance. The bar is high and the failure asymmetric — a
missed match costs a re-drag, a wrong match moves tier intent onto the wrong
concept — so when unsure, do not match. Runs on the dedicated ``match_model``
(defaults to the synthesis tier, not the cheap first-pass model — see AISettings).
"""

from __future__ import annotations

import json

from app.ai.analysis import derive_prompt_version
from app.ai.pricing import PassCost, cost_usd
from app.ai.prompt_fragments import INJECTION_GUARD_NOTE
from app.ai.provider import AIProvider, DeltaSink
from app.ai.schemas import DimensionMatchReport, PoolDimensionReport
from app.schemas.settings import AppSettings

SYSTEM_PROMPT = """\
You are reconciling two lists of "dimensions" — axes along which a pool of housing co-op applicants varies. One is from a PRIOR analysis, one freshly discovered from the same (slightly changed) pool; they overlap heavily but wording may differ and some axes may be new or gone.
Your only job: identify which NEW dimension means the SAME THING as which PRIOR one — a pure identity match. Do not invent, rank, or judge importance.
Match by definitions, not similar words, and only when confident. When in doubt, do NOT match: a missed match is harmless, a wrong match corrupts a human's earlier decision."""

# Static instruction text. Hoisted to a module constant to match the cached passes'
# layout (prompt text at the top, data appended in build_prompt).
# Carries the injection guard even though its inputs are dimension definitions, not raw
# human text: those definitions originated in member-proposed free text, laundered one
# step through discovery — so we guard it like every other prompt.
_INSTRUCTIONS = f"""\
## Task
Reconcile two dimension lists for the same applicant pool: identify which NEW dimension means the SAME underlying concept as which PRIOR dimension.

## Inputs
The two lists, in the `<prior_dimensions>` and `<new_dimensions>` blocks below.

## How to judge
Judge by the definitions, not by whether the keys or names look alike — see the matching bar above. The trap is a pair that shares a name but has DRIFTED to a different concept: reworded — or merely NARROWER/BROADER in scope — but the same underlying concept → match; genuinely different thing measured → do NOT match, even under a near-identical label. Ask "would these two definitions score the TYPICAL applicant the same way?" — if a plausible applicant would land high on one and low on the other, they are different concepts, but do not hunt for an edge case. (Out-of-domain illustration, do not borrow the subject: prior "engine reliability" vs. new "engine reliability" both about a car's motor → match; but prior "fuel efficiency" vs. new "environmental footprint" both nod at being green, yet a thirsty EV scores low on the first and high on the second → different concept, do not match.)

## Output
Return the high-confidence identity matches: one entry (new_key + matching old_key) per NEW dimension that clearly means the same as a PRIOR one. Omit any you are not confident maps to a specific PRIOR dimension — those are treated as genuinely new. Each NEW dimension maps to at most one PRIOR dimension.

## Guardrails
- {INJECTION_GUARD_NOTE}"""

# Prompt identity, derived from the static prompt text. This pass is UNCACHED, but it
# still has a version: it is folded into the run's rank-inputs fingerprint (see
# rank_inputs_fingerprint in services/analysis.py) so editing this prompt makes
# Rank show "out of date".
PROMPT_VERSION = derive_prompt_version(SYSTEM_PROMPT, _INSTRUCTIONS)


def _dimensions_block(tag: str, report: PoolDimensionReport) -> str:
    """A compact JSON list of a report's dimensions, wrapped in an XML tag for the
    prompt. Keys are included so the model can return them, but it matches on
    meaning, not wording.
    """
    dims = [
        {"key": d.key, "name": d.name, "definition": d.definition}
        for d in report.dimensions
    ]
    return f"<{tag}>\n{json.dumps(dims, indent=2, default=str)}\n</{tag}>"


def build_prompt(old: PoolDimensionReport, new: PoolDimensionReport) -> str:
    return (
        f"{_INSTRUCTIONS}"
        f"\n\n{_dimensions_block('prior_dimensions', old)}"
        f"\n\n{_dimensions_block('new_dimensions', new)}"
    )


# --- Cost estimation (non-prompt) ---

# Flat token weight to fold the single match call's (small) cost into the pre-run
# Rank estimate. A generous flat guess, not self-tuning (the pass is uncached and
# runs at most once per re-rank).
MATCH_INPUT_TOKENS = 2000
MATCH_OUTPUT_TOKENS = 600


def estimate_match(settings: AppSettings) -> float:
    """Projected cost of the one identity-match call. Only meaningful when a prior
    run exists (otherwise the pass is skipped at no cost — see ``match_dimensions``).
    """
    from app.ai.provider import Usage

    return cost_usd(
        settings.ai.match_model,
        Usage(input_tokens=MATCH_INPUT_TOKENS, output_tokens=MATCH_OUTPUT_TOKENS),
    )


def match_dimensions(
    provider: AIProvider,
    *,
    old: PoolDimensionReport,
    new: PoolDimensionReport,
    settings: AppSettings,
    on_delta: DeltaSink | None = None,
) -> tuple[dict[str, str], str | None, PassCost]:
    """Map new dimension keys to prior ones at a high confidence bar.

    Returns ``(new_key -> old_key, narrative, cost)``. The result is sanitized so it is
    a function of ``new_key`` over real keys (each NEW dimension adopts at most one PRIOR;
    unknown keys dropped), so it can't corrupt the carry-forward. Several new keys MAY map
    to the SAME old key — a prior axis re-carved into twins this run — which
    ``adopt_matched_keys`` collapses onto the one prior key. Any key present in BOTH lists
    is force-mapped to itself (the frozen-key invariant — see below), overriding the model
    for those keys. An empty map (first run, or no matches) is common.

    ``on_delta``, when given, streams the model's reasoning text as it generates,
    so the criteria phase's live "thinking" continues through the match call too.
    """
    if not old.dimensions or not new.dimensions:
        return {}, None, PassCost()

    result = provider.structured_output(
        model_id=settings.ai.match_model,
        schema=DimensionMatchReport,
        prompt=build_prompt(old, new),
        system_prompt=SYSTEM_PROMPT,
        on_delta=on_delta,
    )
    report: DimensionMatchReport = result.output

    old_keys = {d.key for d in old.dimensions}
    new_keys = {d.key for d in new.dimensions}
    mapping: dict[str, str] = {}
    for m in report.matches:
        # Keep only matches over real keys; first valid wins per new key. The map is
        # a function of new_key (each NEW dimension adopts at most one PRIOR), but the
        # SAME prior key MAY be claimed by several new keys: when discovery re-carves one
        # prior axis into multiple twins this run, all of them are the same prior concept
        # and collapse onto it in adopt_matched_keys (which de-dupes the shared key). A
        # prior axis is committee-established, so folding re-carvings back into it reuses
        # its cached score rather than double-weighting one concept.
        if m.new_key not in new_keys or m.old_key not in old_keys:
            continue
        if m.new_key in mapping:
            continue
        mapping[m.new_key] = m.old_key

    # Deterministic self-match: any key present in BOTH lists IS its own prior axis by the
    # frozen-key invariant (a key is its frozen concept — definition/poles/scores never
    # change under a key). So force key→key, overriding any LLM opinion for those keys. This
    # is the strongest possible identity signal (exact key equality), stronger than any
    # definitional judgement, so we assert it in code rather than trust the model. Two
    # guarantees ride on it: (1) a committee-KEPT axis (injected at decomposition, so present
    # in both lists) can never be matched onto a DIFFERENT prior key and vanish; (2) a scored
    # key the decomposer reworded still adopts its FROZEN prior text wholesale downstream
    # (adopt_matched_keys), so text and cached score stay consistent. The LLM still governs
    # every DRIFTED key (its real job — mapping reworded keys back to canonical).
    for key in new_keys & old_keys:
        mapping[key] = key

    return mapping, result.narrative, PassCost.from_usage(result.model_id, result.usage)
