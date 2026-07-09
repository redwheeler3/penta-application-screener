"""Dimension reconcile: the second look at dropped prior dimensions on a re-rank
(SPEC "Automatic Reconcile Of Dropped Dimensions").

Discovery re-discovers blind; the match pass carries forward the dimensions that
re-surfaced on their own. This pass takes the priors that did NOT re-surface and
asks, against the current pool: "does this axis still meaningfully VARY here?" —
so a factor the committee once cared about isn't silently lost when a fresh
discovery run happens not to name it.

The shape mirrors the match pass run in reverse, but NOT its economics: match is a
pure text-vs-text identity compare that never sees the pool (~2k tokens); reconcile
must read a compressed pool view to answer "does the pool vary on this?", so it
takes a pool-sized input (the same shared digest discovery uses).

The judgment bar is HARDER than discovery's, deliberately. Being shown "what about
these?" biases a model toward yes (the same over-confidence the match pass showed on
drifted concepts), and these axes already failed one test — fresh discovery just
looked at this pool and declined to name them. So "no" is the expected answer for
most: revive only when the pool genuinely varies on the axis. The full ballot (a
reasoned verdict per offered prior, both ways) is the ``reconcile_audit`` trail.
"""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.ai.analysis import derive_prompt_version
from app.ai.pool_digest import INPUT_TOKENS_PER_CANDIDATE, pool_digest_block
from app.ai.pricing import cost_usd
from app.ai.prompt_fragments import INJECTION_GUARD_NOTE
from app.ai.provider import AIProvider, DeltaSink, Usage
from app.ai.schemas import PoolDimension, ReconcileReport
from app.db.models import Application
from app.schemas.settings import AppSettings

KIND = "dimension_reconcile"  # for logging / the debug view; not a cached per-app kind

SYSTEM_PROMPT = """\
You are helping a housing co-op screening committee decide whether an axis the committee cared about in the PAST still applies to the CURRENT applicant pool.
A fresh analysis of this pool just ran and did NOT surface these axes on its own. Your job is a skeptical second look: for each dropped axis, does THIS pool genuinely VARY on it — do applicants spread out, so the axis would actually separate them?
Default to NO. These axes already failed one test (fresh discovery declined to name them), and being asked "what about this one?" is not evidence it applies. Revive an axis ONLY when the pool in front of you clearly varies on it. A flat axis (applicants all similar) or one that does not apply to this pool is a no — and "no" should be your answer for most of them."""

# Static instruction text. Hoisted to a module constant to match the other passes'
# layout (prompt text at the top, data appended in build_prompt). Carries the
# injection guard: the dropped-dimension definitions originated in member-proposed
# free text laundered through discovery, and the pool digest is applicant text.
_INSTRUCTIONS = f"""\
## Task
For each PRIOR dimension in the `<dropped_dimensions>` block, judge against the pool in `<applicant_pool>`: does this pool meaningfully VARY on that axis? Return one verdict per dropped dimension.

## Inputs
- `<dropped_dimensions>`: axes from earlier analyses of this (evolving) pool that the latest fresh discovery did not re-surface. Each has a key, name, and definition.
- `<applicant_pool>`: the current eligible applicants, each with structured "facts" and an essay summary — the same view discovery reads.

## How to judge
- Ask ONLY "do applicants spread out on this axis in THIS pool?" — not "is this a nice thing to care about". An axis everyone scores the same on (all high, all low, all middling) does NOT vary: it cannot move a ranking, so revive is false.
- You are NOT weighing importance and NOT matching to other dimensions. Pure applicability: does the pool vary on it, yes or no.
- Resist the pull to say yes because the axis sounds reasonable or the committee once valued it. Fresh discovery already read this pool and did not name these — treat that as the strong prior it is. Revive is the exception, not the rule.
- Judge from the pool you were shown, not from what a co-op "should" value. If the evidence to place applicants on the axis is not in the pool, that is a no (not present).

## Output
For each dropped dimension: its `old_key`, a boolean `revive`, and one sentence of `reasoning` grounded in the pool (a "no" should say why — flat, not present, or not applicable). Include EVERY dropped dimension exactly once.

## Guardrails
- {INJECTION_GUARD_NOTE}
- Do not score or name individual applicants. Judge the axis against the pool as a whole."""

# Prompt identity, derived from the static prompt text. This pass is UNCACHED, but
# it still has a version folded into the run's rank-inputs fingerprint (see
# rank_inputs_fingerprint in services/ranking_run.py), so editing this prompt makes
# Rank show "out of date".
PROMPT_VERSION = derive_prompt_version(SYSTEM_PROMPT, _INSTRUCTIONS)


def _dropped_block(dropped: list[PoolDimension]) -> str:
    """The dropped prior dimensions as a compact JSON list, wrapped in an XML tag.
    Only key/name/definition — reconcile judges the axis, not its prior wording.
    """
    dims = [
        {"key": d.key, "name": d.name, "definition": d.definition} for d in dropped
    ]
    return f"<dropped_dimensions>\n{json.dumps(dims, indent=2, default=str)}\n</dropped_dimensions>"


def build_prompt(
    db: Session, *, dropped: list[PoolDimension], applications: list[Application]
) -> str:
    return (
        f"{_INSTRUCTIONS}"
        f"\n\n{_dropped_block(dropped)}"
        f"\n\n{pool_digest_block(db, applications)}"
    )


# --- Cost estimation (non-prompt) ---

# Per-dropped-dimension output allowance for the pre-run estimate: the ballot emits a
# verdict + one reasoning sentence per OFFERED prior, so output scales with the
# dropped set, not the revived set. Input is the shared per-candidate pool weight.
_RECONCILE_OUTPUT_TOKENS_PER_DIMENSION = 120


def estimate_reconcile(
    dropped_count: int, applications: list[Application], settings: AppSettings
) -> float:
    """Projected cost of the single reconcile call: pool-sized input (same digest as
    discovery) plus a per-dropped-dimension output allowance for the ballot. Zero
    when there is nothing dropped (the pass is skipped — see ``reconcile_dropped``).
    """
    if dropped_count <= 0:
        return 0.0
    usage = Usage(
        input_tokens=INPUT_TOKENS_PER_CANDIDATE * len(applications),
        output_tokens=_RECONCILE_OUTPUT_TOKENS_PER_DIMENSION * dropped_count,
    )
    return cost_usd(settings.ai.reconcile_model, usage)


def reconcile_dropped(
    provider: AIProvider,
    db: Session,
    *,
    dropped: list[PoolDimension],
    applications: list[Application],
    settings: AppSettings,
    on_delta: DeltaSink | None = None,
) -> tuple[list[str], list[dict], str | None, float]:
    """Ask the model which dropped prior dimensions the current pool still varies on.

    Returns ``(revive_keys, ballot, narrative, cost_usd)``:
      - ``revive_keys`` — the sanitized set of old_keys to pull back into the run
        (one-to-one over real dropped keys; a verdict on an unknown/duplicate key is
        dropped, and only ``revive: true`` verdicts count).
      - ``ballot`` — every verdict as a dict ``{old_key, revive, reasoning}``, for the
        ``reconcile_audit`` trail (both revivals and rejections, per RQ8b).
      - ``narrative`` / ``cost_usd`` — the model's reasoning text and the priced call.

    Skipped (empty results, no call, zero cost) when nothing is dropped — e.g. a
    first run, or a re-run where the match pass carried everything forward.
    """
    if not dropped or not applications:
        return [], [], None, 0.0

    result = provider.structured_output(
        model_id=settings.ai.reconcile_model,
        schema=ReconcileReport,
        prompt=build_prompt(db, dropped=dropped, applications=applications),
        system_prompt=SYSTEM_PROMPT,
        on_delta=on_delta,
    )
    report: ReconcileReport = result.output

    dropped_keys = {d.key for d in dropped}
    revive_keys: list[str] = []
    ballot: list[dict] = []
    seen: set[str] = set()
    for v in report.verdicts:
        # Keep one verdict per real dropped key; first wins, unknown/duplicate dropped.
        if v.old_key not in dropped_keys or v.old_key in seen:
            continue
        seen.add(v.old_key)
        ballot.append({"old_key": v.old_key, "revive": v.revive, "reasoning": v.reasoning})
        if v.revive:
            revive_keys.append(v.old_key)

    return revive_keys, ballot, result.narrative, cost_usd(result.model_id, result.usage)
