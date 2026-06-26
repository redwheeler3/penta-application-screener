"""Dimension identity matching: map a freshly-discovered dimension set onto the
prior run's, so tier placements and cached scores carry forward across a re-rank
(SPEC "Tier Carry-Forward On Re-Rank").

Discovery re-discovers dimensions *blind*; this pass then answers a narrow identity
question: which new dimension is the same concept as which old one? It recognizes
sameness, never weighs importance. The bar is high and the failure asymmetric — a
missed match costs a re-drag, a wrong match moves tier intent onto the wrong
concept — so when unsure, do not match. Runs on the first-pass model.
"""

from __future__ import annotations

import json

from app.ai.pricing import cost_usd
from app.ai.provider import AIProvider, DeltaSink
from app.ai.schemas import DimensionMatchReport, PoolPatternReport
from app.schemas.settings import AppSettings

KIND = "dimension_matching"  # for logging / the debug view; not a cached per-app kind

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
        settings.ai.first_pass_model,
        Usage(input_tokens=MATCH_INPUT_TOKENS, output_tokens=MATCH_OUTPUT_TOKENS),
    )

SYSTEM_PROMPT = """\
You are reconciling two lists of "dimensions" — axes along which a pool of housing co-op applicants varies. One list is from a PRIOR analysis, one is freshly discovered from the same (slightly changed) pool. They overlap heavily but the wording may differ and some axes may be genuinely new or gone.
Your only job is to identify which NEW dimension means the SAME THING as which PRIOR dimension — a pure identity match. You do not invent dimensions, rank them, or judge which matter.
Match only when you are confident the two describe the same underlying concept, judging by their definitions, not just similar words. When in doubt, do NOT match: a missed match is harmless, a wrong match corrupts a human's earlier decision. Every match must be one-to-one."""


def _dimensions_block(label: str, report: PoolPatternReport) -> str:
    """A compact JSON list of a report's dimensions for the prompt. Keys are
    included so the model can return them, but it matches on meaning, not wording.
    """
    dims = [
        {"key": d.key, "name": d.name, "definition": d.definition}
        for d in report.dimensions
    ]
    return f"{label}:\n{json.dumps(dims, indent=2, default=str)}"


def build_prompt(old: PoolPatternReport, new: PoolPatternReport) -> str:
    return f"""\
Below are two dimension lists for the same applicant pool.

{_dimensions_block("PRIOR dimensions", old)}

{_dimensions_block("NEW dimensions", new)}

Return the high-confidence identity matches: for each NEW dimension that clearly means the same thing as a PRIOR dimension, one entry with its new_key and the matching old_key. Judge by the definitions, not by whether the keys or names look alike. Omit any NEW dimension you are not confident maps to a specific PRIOR dimension — those are treated as genuinely new. Matches must be strictly one-to-one (no prior or new dimension used twice)."""


def match_dimensions(
    provider: AIProvider,
    *,
    old: PoolPatternReport,
    new: PoolPatternReport,
    settings: AppSettings,
    on_delta: DeltaSink | None = None,
) -> tuple[dict[str, str], str | None, float]:
    """Map new dimension keys to prior ones at a high confidence bar.

    Returns ``(new_key -> old_key, narrative, cost_usd)``. The result is sanitized
    to strictly one-to-one over real keys, so a duplicate or unknown key can't
    corrupt the carry-forward. An empty map (first run, or no matches) is common.

    ``on_delta``, when given, streams the model's reasoning text as it generates,
    so the criteria phase's live "thinking" continues through the match call too.
    """
    if not old.dimensions or not new.dimensions:
        return {}, None, 0.0

    result = provider.structured_output(
        model_id=settings.ai.first_pass_model,
        schema=DimensionMatchReport,
        prompt=build_prompt(old, new),
        system_prompt=SYSTEM_PROMPT,
        on_delta=on_delta,
    )
    report: DimensionMatchReport = result.output

    old_keys = {d.key for d in old.dimensions}
    new_keys = {d.key for d in new.dimensions}
    mapping: dict[str, str] = {}
    used_old: set[str] = set()
    for m in report.matches:
        # Keep only clean one-to-one matches over real keys; first valid wins.
        if m.new_key not in new_keys or m.old_key not in old_keys:
            continue
        if m.new_key in mapping or m.old_key in used_old:
            continue
        mapping[m.new_key] = m.old_key
        used_old.add(m.old_key)

    return mapping, result.narrative, cost_usd(result.model_id, result.usage)
