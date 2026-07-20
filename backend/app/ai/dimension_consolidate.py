"""Post-score dimension consolidation: heal duplicate dimension keys the match pass
can't (SPEC "Matching scope" → "Post-score consolidation").

Matching runs *before* scoring and decides on definitions alone, at a high bar — so it
occasionally lets a re-worded concept through as a fresh key next to an established one.
Once both are established priors, no later match dares merge them, and the duplicate
persists forever. This pass runs *after* scoring, where a new signal exists: every
dimension now has a per-applicant score vector, and a genuine duplicate reveals itself
as a near-identical vector (high Pearson r).

Two stages, because correlation is a good net but a bad verdict (distinct axes can
correlate — engaged applicants score high on both "why you're here" and "do you finish
things"): (1) NOMINATE — deterministic, free: flag pairs at r ≥ threshold, comparing this
run's keys against all known keys' cached vectors; (2) CONFIRM — one cheap LLM call that
judges the flagged pairs by their DEFINITIONS and merges only true duplicates. Merging
aliases the newer key to the older/canonical one (see ``dimension_alias`` + the merge
mechanic in ``ranking_run``), so scores and tier placement follow the survivor and the
match pass adopts the canonical key on future runs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from app.ai.analysis import derive_prompt_version
from app.ai.pricing import PassCost, cost_usd
from app.ai.prompt_fragments import INJECTION_GUARD_NOTE
from app.ai.provider import AIProvider, DeltaSink, Usage
from app.ai.schemas import ConsolidationReport, PoolDimensionReport
from app.ai.score_vectors import CORRELATION_THRESHOLD, correlation
from app.schemas.settings import AppSettings


@dataclass(frozen=True)
class NominatedPair:
    """A correlation-flagged candidate pair, oriented canonical-first (``keep`` is the
    older/established key, ``drop`` the newer one that would be aliased away on merge)."""

    keep: str
    drop: str
    r: float


def nominate_pairs(
    run_keys: list[str],
    canonical_rank: dict[str, int],
    vectors: dict[str, dict[int, float]],
    threshold: float = CORRELATION_THRESHOLD,
) -> list[NominatedPair]:
    """Deterministic stage: flag pairs whose score vectors correlate at ``r >=
    threshold``, where at least one key is in THIS run (``run_keys``). Comparing this
    run's keys against every known key (not just this run's) is what heals a fork even
    on a run where only one variant surfaced — the fresh key correlates against the
    prior key's cached vector.

    ``canonical_rank`` orders keys oldest→newest (lower = older = wins on merge), so
    each pair is oriented ``keep`` (older) / ``drop`` (newer). It also defines the set of
    LIVE keys — keys present in some current dimension report. Only live keys are
    nominated: ``vectors`` retains score rows for keys already merged away (a dropped
    key's cached scores live forever), and those would correlate against their own
    survivor and get re-nominated with no definition to judge — a phantom re-merge of a
    dead key. Gating on ``canonical_rank`` membership drops them. Free — no model call.
    """
    live = set(canonical_rank)
    # Prior-side candidates: live keys with a score vector (a dead key is absent from
    # `live`; a live key with no vector can't correlate). run_keys are always live.
    candidates = [k for k in vectors if k in live]
    seen: set[frozenset[str]] = set()
    pairs: list[NominatedPair] = []
    for a in run_keys:  # one side is always a this-run key
        if a not in live:  # this run is persisted before key_history, so normally present
            continue
        for b in candidates:
            if a == b:
                continue
            fs = frozenset((a, b))
            if fs in seen:  # a run×run pair is reachable twice; emit once
                continue
            seen.add(fs)
            r = correlation(a, b, vectors)
            if r is None or r < threshold:
                continue
            # Older key (smaller rank) is kept. Both keys are live, so both have a rank.
            keep, drop = (a, b) if canonical_rank[a] <= canonical_rank[b] else (b, a)
            pairs.append(NominatedPair(keep=keep, drop=drop, r=r))
    pairs.sort(key=lambda p: p.r, reverse=True)  # worst-duplicate first, for the audit
    return pairs


SYSTEM_PROMPT = """\
You are auditing a set of "dimensions" — axes along which a pool of housing co-op applicants varies — for duplicates that should be merged into one.
You are given PAIRS that already score applicants near-identically (their per-applicant scores move together closely). That near-identical scoring is strong evidence they are the same axis, so the DEFAULT is to merge — unless the definitions reveal they are genuinely distinct axes that merely correlate (a confound: the same kind of applicant happens to score high on both).
Lean toward merging. Merging a pair that already scores alike costs almost nothing (the surviving axis represents both). Keep a pair apart only when you can name a concrete, real way they diverge — not a faint hypothetical — because a needless split leaves the committee weighing one concept twice."""

_INSTRUCTIONS = f"""\
## Task
For each pair in the `<candidate_pairs>` block, decide whether to MERGE the two dimensions into one (same underlying concept) or KEEP them apart (genuinely distinct axes that only correlate). Default to merge.

## How to judge
- Judge by the definitions, not by whether the names or keys look alike. Ask "would these two definitions score the SAME applicant the same way, for the same reason?" — for pairs that already score alike, the answer is usually yes: merge.
- **Keep apart ONLY for a concrete confound:** you must be able to name a plausible applicant who lands genuinely HIGH on one and LOW on the other, for a real reason. (Out-of-domain illustration, do not borrow the subject: "arrives on time" and "dresses neatly" correlate — conscientious people do both — but a punctual slob lands high on one, low on the other, so they are distinct axes.) A faint or hypothetical difference is not enough to keep apart.
- The bar is asymmetric on purpose: a needless merge only loses resolution between two axes that already score alike, while a needless split leaves a real duplicate. So when it's close, MERGE.

## Output
One verdict per pair: `key_a`, `key_b`, `same_concept` (true = merge; false only for a concrete confound), and a one-sentence `reason` (for a merge, the score-alike assertion; for a keep-apart, the specific applicant who diverges).

## Guardrails
- {INJECTION_GUARD_NOTE}"""

PROMPT_VERSION = derive_prompt_version(SYSTEM_PROMPT, _INSTRUCTIONS)


def _pairs_block(pairs: list[NominatedPair], defs: dict[str, str]) -> str:
    payload = [
        {
            "key_a": p.keep,
            "definition_a": defs.get(p.keep, ""),
            "key_b": p.drop,
            "definition_b": defs.get(p.drop, ""),
        }
        for p in pairs
    ]
    return f"<candidate_pairs>\n{json.dumps(payload, indent=2, default=str)}\n</candidate_pairs>"


def build_prompt(pairs: list[NominatedPair], defs: dict[str, str]) -> str:
    return f"{_INSTRUCTIONS}\n\n{_pairs_block(pairs, defs)}"


# --- Cost estimation (non-prompt) ---

# Flat token weight to fold the single confirm call into the pre-run estimate. The call
# runs only when correlation nominates a pair (often none), and judges a handful of
# pairs — so this is a generous ceiling, and the estimator prefers measured history.
CONSOLIDATE_INPUT_TOKENS = 1500
CONSOLIDATE_OUTPUT_TOKENS = 400


def estimate_consolidate(settings: AppSettings) -> float:
    """Projected cost of the one confirm call. Only meaningful when a pair is
    nominated (otherwise the pass makes no model call — see ``consolidate_dimensions``)."""
    return cost_usd(
        settings.ai.consolidate_model,
        Usage(input_tokens=CONSOLIDATE_INPUT_TOKENS, output_tokens=CONSOLIDATE_OUTPUT_TOKENS),
    )


@dataclass(frozen=True)
class Consolidation:
    """Result of the pass: confirmed merges (drop_key -> keep_key), the model's
    narrative, per-pair audit rows, and the confirm-call cost."""

    merges: dict[str, str]
    narrative: str | None
    audit: list[dict]
    cost: PassCost


def consolidate_dimensions(
    provider: AIProvider,
    *,
    report: PoolDimensionReport,
    canonical_rank: dict[str, int],
    vectors: dict[str, dict[int, float]],
    definitions: dict[str, str],
    names: dict[str, str] | None = None,
    settings: AppSettings,
    on_delta: DeltaSink | None = None,
) -> Consolidation:
    """Nominate duplicate pairs by score-vector correlation, then confirm by definition.

    ``definitions`` maps every candidate key (this run's dimensions AND prior keys that
    could be nominated) to its definition, so the confirm prompt can judge a this-run ×
    prior-key pair. ``names`` maps those same keys to their user-facing mint name, captured
    into the audit alongside the definitions so the Insights panel can label each pair by
    name (a merged ``drop`` key is removed from the report right after, so its name — like
    its definition — must be snapshotted here or it's lost). Returns a ``Consolidation``.
    When correlation nominates nothing (the common case), returns empty at zero cost — no
    model call. Otherwise one confirm call adjudicates the flagged pairs; only
    ``same_concept`` verdicts become merges (``drop -> keep``), each aliasing the newer key
    to the older/canonical one.
    """
    names = names or {}
    run_keys = [d.key for d in report.dimensions]
    pairs = nominate_pairs(
        run_keys, canonical_rank, vectors,
        threshold=settings.ai.consolidate_correlation_threshold,
    )
    if not pairs:
        return Consolidation(merges={}, narrative=None, audit=[], cost=PassCost())

    result = provider.structured_output(
        model_id=settings.ai.consolidate_model,
        schema=ConsolidationReport,
        prompt=build_prompt(pairs, definitions),
        system_prompt=SYSTEM_PROMPT,
        on_delta=on_delta,
    )
    verdicts: ConsolidationReport = result.output

    # Index verdicts by unordered key pair so we can match them back to nominations
    # regardless of which order the model echoed the keys.
    verdict_by_pair: dict[frozenset[str], tuple[bool, str]] = {}
    for v in verdicts.verdicts:
        verdict_by_pair[frozenset((v.key_a, v.key_b))] = (v.same_concept, v.reason)

    merges: dict[str, str] = {}
    audit: list[dict] = []
    for p in pairs:
        same, reason = verdict_by_pair.get(frozenset((p.keep, p.drop)), (False, ""))
        # Never alias a key twice, and never merge into a key already being dropped
        # (would create a broken chain); first confirmed verdict for a key wins.
        mergeable = same and p.drop not in merges and p.keep not in merges
        if mergeable:
            merges[p.drop] = p.keep
        audit.append(
            {
                "keep": p.keep,
                "drop": p.drop,
                "r": round(p.r, 3),
                "merged": mergeable,
                "reason": reason,
                # The two definitions the confirm call actually judged — captured here so
                # a KEEP/MERGE decision is self-contained (an eval or reviewer can rebuild
                # what the model compared without spelunking prior runs for the drop key's
                # definition, which is a PRIOR-run key when a fork is healed cross-run and
                # so isn't in this run's report). The eval-relevant artifact, per the
                # capture-to-fixture rule.
                "definition_keep": definitions.get(p.keep, ""),
                "definition_drop": definitions.get(p.drop, ""),
                # The user-facing names, snapshotted for the SAME reason as the definitions:
                # a merged drop key is removed from the report right after, so the Insights
                # panel can't look its name up later. Empty string when a key predates name
                # capture (older run) — the panel then falls back to the bare key.
                "name_keep": names.get(p.keep, ""),
                "name_drop": names.get(p.drop, ""),
            }
        )
    return Consolidation(
        merges=merges,
        narrative=result.narrative,
        audit=audit,
        cost=PassCost.from_usage(result.model_id, result.usage),
    )
