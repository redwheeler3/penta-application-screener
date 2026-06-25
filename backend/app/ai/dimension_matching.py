"""Dimension identity matching: map a freshly-discovered dimension set back onto
the prior run's dimensions, so the committee's tier placements (and cached
scores) carry forward across a re-rank.

This is the second pass of the carry-forward re-rank (SPEC "Tier Carry-Forward On
Re-Rank"). The first pass (``pattern_discovery``) re-discovers dimensions *blind*
— it never sees the prior set, so it cannot anchor on old wording. This pass then
answers a narrow, purely *identity* question: which new dimension is the same
concept as which old one? It does not discover anything and does not weigh
importance (the committee already did that, as tier placements), so it does not
violate "AI discovers what varies; the human decides what matters" — it only
recognizes sameness so the human's decision can ride forward.

The bar is deliberately high and the failure is asymmetric: a *missed* match costs
the committee a re-drag (the survivor lands in Ignore, flagged new); a *wrong*
match would silently move their tier intent onto the wrong concept. So the prompt
instructs: when unsure, do not match. Runs on the first-pass model — this is a
short structured comparison of two short lists, not cross-document synthesis.
"""

from __future__ import annotations

import json

from app.ai.pricing import cost_usd
from app.ai.provider import AIProvider
from app.ai.schemas import DimensionMatchReport, PoolPatternReport
from app.schemas.settings import AppSettings

KIND = "dimension_matching"  # for logging / the debug view; not a cached per-app kind

# Flat token weight for the single match call, used only to fold its (small) cost
# into the pre-run Rank estimate. The call compares two short dimension lists and
# emits a compact match list, so it is far cheaper than a per-candidate scoring
# call; this is a deliberately generous flat guess, not a self-tuning average
# (the match pass is uncached and runs at most once per re-rank).
MATCH_INPUT_TOKENS = 2000
MATCH_OUTPUT_TOKENS = 600


def estimate_match(settings: AppSettings) -> float:
    """Projected cost of the one identity-match call on the first-pass model.

    Only meaningful when a prior run exists (otherwise the match pass is skipped
    and returns an empty map at no cost — see ``match_dimensions``). The caller
    folds this into the combined Rank estimate only in that case.
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
    """A compact JSON list of a report's dimensions for the prompt — name and
    definition only. Keys are included so the model can return them, but it is
    told to match on meaning (definitions), not key wording.
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
) -> tuple[dict[str, str], str | None, float]:
    """Map new dimension keys to prior ones at a high confidence bar.

    Returns ``(new_key -> old_key, narrative, cost_usd)``. Only confident,
    one-to-one matches survive: the result is sanitized so a model that returns a
    duplicate or an unknown key cannot corrupt the carry-forward — extra or
    dangling entries are dropped, first valid wins. An empty map (e.g. a first run
    with no prior set, or no confident matches) is the safe, common case.
    """
    if not old.dimensions or not new.dimensions:
        return {}, None, 0.0

    result = provider.structured_output(
        model_id=settings.ai.first_pass_model,
        schema=DimensionMatchReport,
        prompt=build_prompt(old, new),
        system_prompt=SYSTEM_PROMPT,
    )
    report: DimensionMatchReport = result.output

    old_keys = {d.key for d in old.dimensions}
    new_keys = {d.key for d in new.dimensions}
    mapping: dict[str, str] = {}
    used_old: set[str] = set()
    for m in report.matches:
        # Drop anything that would not be a clean one-to-one match between real
        # keys: unknown keys, a new key already mapped, or an old key already
        # claimed. First valid match for a key wins.
        if m.new_key not in new_keys or m.old_key not in old_keys:
            continue
        if m.new_key in mapping or m.old_key in used_old:
            continue
        mapping[m.new_key] = m.old_key
        used_old.add(m.old_key)

    return mapping, result.narrative, cost_usd(result.model_id, result.usage)
