"""Coverage gate for the Fan-Out Redesign (SPEC "Fan-Out Redesign", Phase 4a).

The bake-off proved the fan-out produces a CLEAN set (0 overlaps) — but a single
discovery run was already clean, so "no overlaps" is not the fan-out's edge. Its
edge is supposed to be COVERAGE: K fresh-context discoveries surface real
differentiators any single run misses. This script measures that, the last
unproven claim gating the redesign.

Definitions, all computed from the cached per-(candidate, dimension) scores the
app already persists (no model calls):
  - REAL differentiator: an axis whose pool score-vector has non-trivial spread
    (stdev ≥ FLAT_FLOOR). A near-flat axis differentiates nobody — padding. On this
    pool only `income_level` (stdev 0.076) is near-flat; the floor sits just above it.
  - DISTINCT TERRITORY: real axes greedily clustered by score-vector correlation
    (≥ SAME_TERRITORY_R = same underlying differentiator). Territory count, not raw
    axis count, is the honest coverage measure — it ignores re-carvings of one axis.

The gate: distinct territory of a SINGLE run vs. the UNION of all runs (the K-fanout
proxy on the historical fixture). If the union covers materially more territory, the
K× discovery cost buys real coverage → the redesign is justified. If it ties a single
run, K buys nothing and we reconsider K / reach for a completeness-critic.

    cd backend && uv run python -m scripts.coverage_gate
"""

from __future__ import annotations

import statistics

from sqlalchemy import select

from app.db.models import RankingRun
from app.db.session import SessionLocal
from scripts.dimension_overlap import _pearson, load_score_vectors

# Only axes with stdev at/above this count as real differentiators. Calibrated to the
# pool: income_level (0.076) is the sole near-flat axis, everything else is ≥ 0.14.
FLAT_FLOOR = 0.10
# Two real axes at/above this vector-correlation cover the SAME territory (a re-carving
# of one differentiator), so they count once. Matches the overlap judge's family sense.
SAME_TERRITORY_R = 0.7
MIN_SUPPORT = 3  # candidates scored on both, for a correlation to mean anything


def _run_keys(run: RankingRun) -> list[str]:
    report = (run.criteria or {}).get("dimension_report") or {}
    return [d["key"] for d in report.get("dimensions", [])]


def _real_keys(keys: list[str], vectors: dict[str, dict[int, float]]) -> list[str]:
    """Keys that are scored AND spread (stdev ≥ floor) — the real differentiators."""
    out = []
    for k in keys:
        v = vectors.get(k)
        if v and statistics.pstdev(list(v.values())) >= FLAT_FLOOR:
            out.append(k)
    return out


def _same_territory(a: str, b: str, vectors: dict[str, dict[int, float]]) -> bool:
    av, bv = vectors[a], vectors[b]
    common = sorted(av.keys() & bv.keys())
    if len(common) < MIN_SUPPORT:
        return False
    r = _pearson([av[c] for c in common], [bv[c] for c in common])
    return r is not None and r >= SAME_TERRITORY_R


def territory_count(keys: list[str], vectors: dict[str, dict[int, float]]) -> int:
    """Distinct differentiating territory covered by ``keys``: real axes greedily
    clustered by score-vector correlation, counted once per cluster. This is coverage
    net of re-carvings — more axes over the same ground does NOT inflate it.
    """
    reals = _real_keys(keys, vectors)
    clusters: list[list[str]] = []
    for k in reals:
        for c in clusters:
            if _same_territory(c[0], k, vectors):
                c.append(k)
                break
        else:
            clusters.append([k])
    return len(clusters)


def main() -> None:
    db = SessionLocal()
    vectors = load_score_vectors(db)
    runs = list(db.scalars(select(RankingRun).order_by(RankingRun.id.asc())))
    db.close()

    if not runs or not vectors:
        print("Need ranking runs with cached scores. Run Sync → Screen → Rank first.")
        return

    run_key_lists = [_run_keys(r) for r in runs]
    singles = [territory_count(ks, vectors) for ks in run_key_lists]

    union_keys: list[str] = []
    for ks in run_key_lists:
        union_keys.extend(ks)
    union_keys = list(dict.fromkeys(union_keys))  # dedupe, preserve order
    union_territory = territory_count(union_keys, vectors)

    mean_single = statistics.mean(singles)
    lift = (union_territory / mean_single - 1) * 100 if mean_single else float("nan")

    print(f"\n{'=' * 68}")
    print("COVERAGE GATE — distinct real-differentiator territory")
    print(f"  (real = score stdev ≥ {FLAT_FLOOR}; same territory = vectors r ≥ {SAME_TERRITORY_R})")
    print(f"{'=' * 68}")
    print(f"  single run, per run : {singles}")
    print(f"  single run, mean    : {mean_single:.1f} distinct territories")
    print(f"  K-union (all runs)  : {union_territory} distinct territories")
    print(f"  coverage lift       : +{lift:.0f}%  (union vs. mean single run)")
    print(f"{'=' * 68}")
    print("Read: a large positive lift = fan-out surfaces real differentiators a single")
    print("run misses → K-parallel justified. A tie = K buys no coverage on this pool.\n")


if __name__ == "__main__":
    main()
