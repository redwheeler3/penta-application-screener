"""Experiment: can a BETTER single discovery call replace the K-parallel fan-out?
(SPEC "Fan-Out Redesign" — Jeff's challenge to D6, 2026-07-09 s2.)

The redesign assumes we need divergence-then-convergence, with divergence coming
from K *fresh-context* discovery calls. Jeff's challenge: get the divergence from
ONE call that over-generates (ask for ~50 dims) and then pare down — cheaper, no
K-orchestration. The within-run data already showed a single call self-deduplicates
(a lone run is ~clean), which predicts over-generation buys FINENESS but not
DIVERSITY (it stays in one framing). This tests that prediction against real Bedrock.

Conditions (each run REPS times — discovery is nondeterministic, so never trust one
sample; the convergence experiment's "wait for the second point" lesson):
  A. normal   — the app's real discovery prompt, unchanged (baseline).
  B. over-gen — same prompt, but asked for ~50 fine dimensions.

Measured WITHOUT scoring (keeps it to a few discovery calls, ~$0.25 total):
  - count + how many distinct CONCEPTS (coverage vs. the known 35-dim union).
  - diversity: does B surface concepts A/prior-runs missed, or just split finer?

Read-only w.r.t. app state — it does NOT persist a run, does NOT touch the real
prompt (so PROMPT_VERSION is untouched and no ranking run is marked stale). Prints a
report and exits.

    cd backend && uv run python -m scripts.exp_single_call_discovery
"""

from __future__ import annotations

from app.ai.pattern_discovery import (
    SYSTEM_PROMPT,
    build_prompt,
    eligible_applications,
)
from app.ai.pricing import cost_usd
from app.ai.schemas import PoolDimensionReport
from app.ai.strands_provider import StrandsProvider
from app.db.session import SessionLocal
from app.services.settings import get_app_settings

REPS = 2  # per condition — enough to see if a result is stable vs. a fluke

# Condition B appends this to the real prompt to push over-generation. Kept here (not
# in the app module) so the shipped PROMPT_VERSION is untouched by the experiment.
OVERGEN_SUFFIX = """

## Experiment override — OVER-GENERATE
For THIS request only, aim HIGH: produce roughly 50 dimensions, splitting each concept
into its finest defensible sub-axes. Do not stop at the usual 10-30. The goal is maximum
coverage and granularity; a later step will pare down and merge. Still obey the
one-concept-per-dimension and grounded-in-evidence rules — fine is good, fabricated is not.
"""


def _discover(provider, db, settings, *, overgen: bool) -> tuple[PoolDimensionReport, float]:
    pool = eligible_applications(db)
    prompt = build_prompt(db, pool)
    if overgen:
        prompt = prompt + OVERGEN_SUFFIX
    result = provider.structured_output(
        model_id=settings.ai.discovery_model,
        schema=PoolDimensionReport,
        prompt=prompt,
        system_prompt=SYSTEM_PROMPT,
    )
    return result.output, cost_usd(result.model_id, result.usage)


def main() -> None:
    db = SessionLocal()
    settings = get_app_settings(db)
    provider = StrandsProvider(
        region=settings.ai.region, max_pool_connections=settings.ai.max_workers
    )
    # Over-gen (~50 dims) streams longer than the app's default 120s read_timeout —
    # that timeout crashed the first attempt (itself a mild "over-gen is heavier"
    # signal). Pre-seed the provider's model cache with a long-timeout BedrockModel
    # for the discovery model so the experiment can complete, WITHOUT touching the
    # shipped provider default. Experiment-local only.
    from botocore.config import Config
    from strands.models import BedrockModel

    provider._models[settings.ai.discovery_model] = BedrockModel(
        model_id=settings.ai.discovery_model,
        region_name=settings.ai.region,
        boto_client_config=Config(
            max_pool_connections=settings.ai.max_workers,
            retries={"max_attempts": 5, "mode": "adaptive"},
            connect_timeout=10,
            read_timeout=600,  # generous headroom for a 50-dimension generation
        ),
    )

    print(f"\n{'=' * 72}")
    print(f"SINGLE-CALL DISCOVERY EXPERIMENT — {REPS} rep(s) per condition")
    print(f"model: {settings.ai.discovery_model}")
    print(f"{'=' * 72}\n")

    # Condition A already ran clean in a prior attempt (gave the cross-call framing
    # answer); pass "b-only" to skip re-paying for it and test only over-gen.
    import sys

    conditions = (("B_overgen", True),) if "b-only" in sys.argv else (
        ("A_normal", False), ("B_overgen", True)
    )

    total_cost = 0.0
    results: dict[str, list[PoolDimensionReport]] = {"A_normal": [], "B_overgen": []}
    try:
        for label, overgen in conditions:
            for rep in range(1, REPS + 1):
                report, cost = _discover(provider, db, settings, overgen=overgen)
                total_cost += cost
                results[label].append(report)
                keys = [d.key for d in report.dimensions]
                print(f"── {label}  rep {rep}  (${cost:.4f})")
                print(f"   dimensions: {len(keys)}")
                print(f"   keys: {sorted(keys)}\n")
    finally:
        db.close()

    # Cross-condition read: does B (over-gen) surface CONCEPTS that A never names, or
    # just split A's concepts finer? Compare key sets (a coarse proxy — same wording ≈
    # same concept; different wording may still be the same concept, flagged for the eye).
    a_keys = {k for r in results["A_normal"] for k in (d.key for d in r.dimensions)}
    b_keys = {k for r in results["B_overgen"] for k in (d.key for d in r.dimensions)}
    print(f"{'=' * 72}")
    print("CROSS-CONDITION")
    print(f"  A (normal)  distinct keys across reps : {len(a_keys)}")
    print(f"  B (overgen) distinct keys across reps : {len(b_keys)}")
    if a_keys:  # only meaningful when A ran this session
        print(f"  in B but not A (exact-key): {len(b_keys - a_keys)}")
        print(f"     {sorted(b_keys - a_keys)}")
        print(f"  in A but not B (exact-key): {len(a_keys - b_keys)}")
        print(f"     {sorted(a_keys - b_keys)}")
    print(f"\n  TOTAL COST (this session): ${total_cost:.4f}")
    print(f"{'=' * 72}\n")
    print("Manual read needed (keys are wording, not concepts): does B's extra count")
    print("come from NEW concepts (diversity — supports Jeff's idea) or FINER splits of")
    print("the same concepts (fineness only — supports K-parallel for diversity)?\n")


if __name__ == "__main__":
    main()
