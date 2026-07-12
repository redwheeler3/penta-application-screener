"""Marginal-coverage analysis for the fan-out K (SPEC "Fan-Out Redesign", Validation 0).

The coverage gate (``coverage_gate.py``) proved K-parallel beats a SINGLE run by
unioning the old sequential runs as a K proxy. This answers the *next* question, the
one gating the K value itself: **on a real fan-out run, does the k-th discoverer still
add territory, or is it paying K× for coverage a smaller K already had?**

Unlike the gate, this needs no cross-run proxy. A real fan-out run stores every
discoverer's raw report (``fan_out_audit``) AND the settled set's ``source_keys`` —
which discoverers fed each settled axis. So within ONE run we can attribute each final
differentiating *territory* back to the discoverers that surfaced it, then compute,
exactly, how much territory a random k-of-K subset would have covered:

    coverage(k) = Σ_territory  P(≥1 of the territory's feeding discoverers is in a
                                random k-subset)
                = Σ_territory  [1 − C(K − support, k) / C(K, k)]

where ``support`` = how many of the K discoverers fed that territory. A territory fed
by many discoverers is caught by almost any k; a territory only one discoverer found
needs that specific discoverer — those are what a larger K buys. The knee in
coverage(k) is where extra discoverers stop surfacing unique territory.

Territory (not raw axis count) is the unit, same as the gate: scored-real settled axes
(score stdev ≥ FLAT_FLOOR) greedily clustered by score-vector correlation
(≥ SAME_TERRITORY_R), so re-carvings of one differentiator count once.

    cd backend && uv run python -m scripts.marginal_coverage
"""

from __future__ import annotations

from math import comb

from sqlalchemy import select

from app.ai.score_vectors import load_score_vectors
from app.db.models import RankingRun
from app.db.session import SessionLocal
from scripts.coverage_gate import (
    FLAT_FLOOR,
    SAME_TERRITORY_R,
    _real_keys,
    _same_territory,
)


def _fan_out_runs(runs: list[RankingRun]) -> list[RankingRun]:
    """Runs that carry a real fan-out audit with per-discoverer reports (K≥2)."""
    out = []
    for r in runs:
        fa = (r.criteria or {}).get("fan_out_audit") or {}
        passes = fa.get("passes") or []
        if fa.get("k") and len(passes) >= 2 and any(
            (p.get("report") or {}).get("dimensions") for p in passes
        ):
            out.append(r)
    return out


def _territory_support(run: RankingRun, vectors: dict[str, dict[int, float]]):
    """Return (K, [support per scored-real territory]) for one fan-out run.

    Each settled axis lists ``source_keys`` — the discoverer keys it absorbed. We map
    each source key to the discoverers whose report contained it, so a settled axis is
    "fed by" the union of those discoverers. We then cluster the scored-real settled
    axes into territories (same rule as the gate) and take each territory's feeders as
    the union across its axes. ``support`` = how many distinct discoverers fed it.
    """
    criteria = run.criteria or {}
    passes = criteria["fan_out_audit"]["passes"]
    # key -> set of discoverer indices that emitted it
    key_to_discoverers: dict[str, set[int]] = {}
    for i, p in enumerate(passes):
        for d in (p["report"]["dimensions"]):
            key_to_discoverers.setdefault(d["key"], set()).add(i)
    k = len(passes)

    # CRITICAL: the match pass runs AFTER decomposition and rewrites settled keys to
    # adopt prior-run keys (so cached scores carry forward). Scores are keyed by the
    # POST-match key, but source_keys/decompose_audit use the PRE-match key. Bridge via
    # match_audit.new_to_old (decompose key -> adopted prior key) so we join to the
    # right score vector. Keys not in the map kept their own name (a genuinely new axis).
    new_to_old = (criteria.get("match_audit") or {}).get("new_to_old") or {}

    settled = criteria["decompose_audit"]["settled"]
    settled_keys = [new_to_old.get(d["key"], d["key"]) for d in settled]
    source_by_settled = {
        new_to_old.get(d["key"], d["key"]): d.get("source_keys", []) for d in settled
    }

    # Keep only scored-real settled axes (differentiating), same floor as the gate.
    reals = set(_real_keys(settled_keys, vectors))
    real_settled = [key for key in settled_keys if key in reals]

    # Cluster real settled axes into territories by score-vector correlation.
    clusters: list[list[str]] = []
    for key in real_settled:
        for c in clusters:
            if _same_territory(c[0], key, vectors):
                c.append(key)
                break
        else:
            clusters.append([key])

    supports: list[int] = []
    for cluster in clusters:
        feeders: set[int] = set()
        for settled_key in cluster:
            for src in source_by_settled.get(settled_key, []):
                feeders |= key_to_discoverers.get(src, set())
        # A territory with no traceable feeder (shouldn't happen) counts as support 1.
        supports.append(len(feeders) or 1)
    return k, supports


def _coverage_at_k(k: int, support: list[int], total_discoverers: int) -> float:
    """Expected territories covered by a random k-of-K discoverer subset."""
    K = total_discoverers
    total = 0.0
    denom = comb(K, k)
    for s in support:
        # P(none of this territory's `s` feeders are in the k-subset)
        miss = comb(K - s, k) / denom if K - s >= k else 0.0
        total += 1 - miss
    return total


def main() -> None:
    db = SessionLocal()
    vectors = load_score_vectors(db)
    runs = _fan_out_runs(list(db.scalars(select(RankingRun).order_by(RankingRun.id.asc()))))
    db.close()

    if not runs:
        print("No real fan-out runs (with per-discoverer reports) found. Run a Rank first.")
        return

    print(f"\n{'=' * 74}")
    print("MARGINAL COVERAGE — expected distinct territory vs. number of discoverers")
    print(f"  (real = score stdev ≥ {FLAT_FLOOR}; same territory = vectors r ≥ {SAME_TERRITORY_R})")
    print("  coverage(k) = expected territories a random k-of-K discoverer subset covers")
    print(f"{'=' * 74}")

    for run in runs:
        k, support = _territory_support(run, vectors)
        full = _coverage_at_k(k, support, k)
        print(f"\n  run {run.id}  (K={k}, {len(support)} real territories settled)")
        print("    territory support histogram (how many discoverers fed each):")
        # compact histogram
        hist = {s: support.count(s) for s in sorted(set(support))}
        print(f"      {hist}   (support 1 = only ONE discoverer surfaced it)")
        print(f"    {'k':>3} | {'coverage(k)':>11} | {'Δ vs k-1':>8} | {'% of full':>9}")
        prev = None
        for kk in range(1, k + 1):
            cov = _coverage_at_k(kk, support, k)
            delta = "" if prev is None else f"{cov - prev:+.2f}"
            print(f"    {kk:>3} | {cov:>11.2f} | {delta:>8} | {cov / full * 100:>8.1f}%")
            prev = cov

    print(f"\n{'=' * 74}")
    print("Read: where Δ vs k-1 goes small, extra discoverers stop surfacing unique")
    print("territory — the knee. A territory with support 1 is the only reason to pay")
    print("for more discoverers; if there are none, K is already past the point of value.\n")


if __name__ == "__main__":
    main()
