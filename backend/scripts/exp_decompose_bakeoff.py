"""Phase 3 bake-off: score decomposition variants with the Phase-1 overlap judge
(SPEC "Fan-Out Redesign", Phase 3).

The redesign's central measured decision: does the multi-agent splitter↔merger↔decider
loop beat the single-call baseline by enough to justify its cost + complexity? This
harness runs a variant M times on the historical fixture (the K discovery reports the
10 locked-pool runs produced — a ready-made fan-out input), and scores each output on:
  - FINEST  — distinct settled axes minus a penalty per un-merged overlapping pair
              (the Phase-1 judge, over score vectors built from each settled axis's
              source keys — a merged axis's vector is the mean of what it absorbed).
  - STABLE  — agreement of the settled set across the M reps on the same input
              (concept clustering by source-key overlap, not raw minted keys).
  - cost, dim count, and how many committee-request axes survived (D9 guard).

Read-only w.r.t. app state (persists nothing). Real Bedrock — confirm spend first.

    cd backend && uv run python -m scripts.exp_decompose_bakeoff [reps] [k]

``reps`` defaults to 3 (never trust one sample — the convergence experiment's lesson).
``k`` caps how many historical reports feed the decomposition (default: all).
"""

from __future__ import annotations

import statistics
import sys

from sqlalchemy import select

from app.ai.dimension_decompose import (
    decompose_dimensions,
    decompose_dimensions_loop,
)
from app.ai.schemas import DecompositionReport, PoolDimensionReport
from app.ai.strands_provider import StrandsProvider
from app.db.models import RankingRun
from app.db.session import SessionLocal
from app.services.settings import get_app_settings
from scripts.dimension_overlap import (
    DEFAULT_OVERLAP_THRESHOLD,
    load_score_vectors,
    overlap_report,
)


def _historical_reports(db, k: int | None) -> list[PoolDimensionReport]:
    """The K carvings of the locked pool: each run's stored discovery report. These
    are the same-pool, different-granularity inputs a real fan-out would produce —
    a free, ready-made fixture (no new discovery calls needed to bake off).
    """
    runs = list(db.scalars(select(RankingRun).order_by(RankingRun.id.asc())))
    reports: list[PoolDimensionReport] = []
    for run in runs:
        payload = (run.criteria or {}).get("dimension_report")
        if payload:
            reports.append(PoolDimensionReport.model_validate(payload))
    return reports[:k] if k else reports


def _settled_vectors(
    report: DecompositionReport, base: dict[str, dict[int, float]]
) -> dict[str, dict[int, float]]:
    """Build a score vector per SETTLED axis from its source keys' cached vectors —
    a merged axis's vector is the per-candidate MEAN of what it absorbed. Lets the
    overlap judge score a settled set whose keys were never scored directly (the
    timing gotcha: settled keys are minted before scoring). Settled axes whose sources
    have no cached scores are skipped (can't be judged).
    """
    out: dict[str, dict[int, float]] = {}
    for dim in report.dimensions:
        srcs = [base[k] for k in dim.source_keys if k in base]
        if not srcs:
            continue
        app_ids = set().union(*[set(v.keys()) for v in srcs])
        out[dim.key] = {
            aid: statistics.mean([v[aid] for v in srcs if aid in v])
            for aid in app_ids
            if any(aid in v for v in srcs)
        }
    return out


def _concept_signature(report: DecompositionReport) -> frozenset[frozenset[str]]:
    """The set of source-key CLUSTERS a decomposition formed — its identity for the
    stability comparison. Compares WHAT got grouped, not the minted keys (which vary
    run to run). Two reps are identical iff they cluster the same source keys together.
    """
    return frozenset(frozenset(d.source_keys) for d in report.dimensions)


def _jaccard(a: frozenset, b: frozenset) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def main() -> None:
    # argv: [reps] [k] [which]  — which ∈ {both, baseline, loop} (default both).
    # `loop` alone lets us re-measure just the loop and compare to a banked baseline,
    # since each Bedrock rep costs real money and the baseline result is stable.
    reps = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    k = int(sys.argv[2]) if len(sys.argv) > 2 else None
    which = sys.argv[3] if len(sys.argv) > 3 else "both"

    db = SessionLocal()
    settings = get_app_settings(db)
    reports = _historical_reports(db, k)
    base_vectors = load_score_vectors(db)
    db.close()

    provider = StrandsProvider(
        region=settings.ai.region, max_pool_connections=settings.ai.max_workers
    )
    # Decomposing ~250 input dims into a large reasoned set streams past the app's
    # default 120s read_timeout (observed — same wall the over-gen experiment hit).
    # Pre-seed a long-timeout model, experiment-local. NOTE for Phase 4: the production
    # decomposition call will need a longer read_timeout than discovery's default.
    from botocore.config import Config
    from strands.models import BedrockModel

    provider._models[settings.ai.discovery_model] = BedrockModel(
        model_id=settings.ai.discovery_model,
        region_name=settings.ai.region,
        boto_client_config=Config(
            max_pool_connections=settings.ai.max_workers,
            retries={"max_attempts": 5, "mode": "adaptive"},
            connect_timeout=10,
            read_timeout=600,
        ),
    )

    input_dims = sum(len(r.dimensions) for r in reports)
    print(f"\n{'=' * 72}")
    print(f"DECOMPOSITION BAKE-OFF — baseline vs. merger↔splitter loop, {reps} rep(s)")
    print(f"input: {len(reports)} reports, {input_dims} total input dims; "
          f"judge r ≥ {DEFAULT_OVERLAP_THRESHOLD}")
    print(f"{'=' * 72}")

    def _baseline_call():
        report, _narr, cost = decompose_dimensions(
            provider, reports=reports, settings=settings
        )
        return report, cost

    def _loop_call():
        report, _audit, cost = decompose_dimensions_loop(
            provider, reports=reports, settings=settings
        )
        return report, cost

    results = []
    if which in ("both", "baseline"):
        results.append(_run_variant("single-call baseline", _baseline_call, reps, base_vectors))
    if which in ("both", "loop"):
        results.append(_run_variant("merger↔splitter loop", _loop_call, reps, base_vectors))

    print(f"{'=' * 72}")
    print("VERDICT")
    print(f"  {'variant':<22}{'stability':>10}{'mean overlaps':>15}{'mean dims':>11}{'cost':>9}")
    for v in results:
        print(f"  {v['label']:<22}{v['stability']:>10.2f}{v['mean_overlaps']:>15.1f}"
              f"{v['mean_dims']:>11.1f}{('$' + format(v['cost'], '.2f')):>9}")
    print()
    print("Decision rule (D7): adopt the loop ONLY if it beats the baseline by a margin")
    print("that justifies its extra cost + complexity — else ship the baseline.\n")


def _run_variant(label, call, reps, base_vectors) -> dict:
    """Run one decomposition variant ``reps`` times, print per-rep judge scores, and
    return {label, stability, mean_overlaps, mean_dims, cost}. ``call`` returns
    ``(report, cost)``.
    """
    print(f"\n── {label} " + "─" * (68 - len(label)))
    outputs: list[DecompositionReport] = []
    overlaps_per_rep: list[int] = []
    total_cost = 0.0
    for rep in range(1, reps + 1):
        # A transient Bedrock read-timeout on one rep shouldn't waste the whole run
        # (and the money already spent on other reps) — skip the failed rep, keep going.
        try:
            report, cost = call()
        except Exception as exc:
            print(f"   rep {rep}: FAILED ({type(exc).__name__}: {exc}) — skipped")
            continue
        total_cost += cost
        outputs.append(report)
        sv = _settled_vectors(report, base_vectors)
        judged = overlap_report(sv, list(sv.keys()))
        overlaps_per_rep.append(len(judged.overlaps))
        merges = sum(1 for d in report.dimensions if len(d.source_keys) > 1)
        reqs = sum(1 for d in report.dimensions if d.from_committee_request)
        print(f"   rep {rep}: {len(report.dimensions)} dims ({merges} merges), "
              f"{len(judged.overlaps)} overlap pair(s), finest {judged.finest_score:.1f}, "
              f"reqs kept {reqs}  (${cost:.4f})")

    if not outputs:  # every rep failed
        return {"label": label, "stability": float("nan"), "mean_overlaps": float("nan"),
                "mean_dims": float("nan"), "cost": total_cost}
    sigs = [_concept_signature(o) for o in outputs]
    pairwise = [
        _jaccard(sigs[i], sigs[j])
        for i in range(len(sigs))
        for j in range(i + 1, len(sigs))
    ]
    stability = statistics.mean(pairwise) if pairwise else float("nan")
    counts = [len(o.dimensions) for o in outputs]
    return {
        "label": label,
        "stability": stability,
        "mean_overlaps": statistics.mean(overlaps_per_rep),
        "mean_dims": statistics.mean(counts),
        "cost": total_cost,
    }


if __name__ == "__main__":
    main()
