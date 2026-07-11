"""Cross-run convergence readout for the locked-pool accumulation experiment
(SPEC "Validation Experiments To Run" #1).

Read-only. Reads every RankingRun from the local DB, oldest→newest, and prints
what the experiment needs but no endpoint/UI exposes (the audit endpoints only
ever show the *current* run): does the dimension set CONVERGE or CREEP across
repeated runs on a locked pool?

Run it after a Sync → Screen → Rank → Rank → Rank sequence on an UNCHANGED pool:

    cd backend && uv run python -m scripts.analyze_convergence

Columns/sections it prints, per run and cumulatively:
  - dimension keys this run produced (post-adopt, i.e. the stored report)
  - NEW keys vs. the running union of all prior runs (the creep signal)
  - distinct-key count this run + cumulative-union count (convergence signal:
    a converging set adds few/no new keys per run; a creeping set keeps growing)
  - decomposition settle-down: input axes → settled count (merges)
  - match carry-forward rate (per the existing match_audit)
  - overlap readout (the Fan-Out Redesign judge): how many of the cumulative-union
    dimensions have score vectors that correlate above threshold — the redundancy
    the creep produced, measured. Delegated to ``scripts.dimension_overlap`` (O2);
    this script only prints the summary line so both stay in sync.

This is an analysis tool, not app code — it computes nothing the app relies on,
so it stays deliberately simple and prints a human-readable report.
"""

from __future__ import annotations

from sqlalchemy import select

from app.db.models import RankingRun
from app.db.session import SessionLocal
from scripts.dimension_overlap import load_score_vectors, overlap_report


def _dim_keys(run: RankingRun) -> list[str]:
    """The dimension keys the run's stored report produced (post key-adoption)."""
    report = (run.criteria or {}).get("dimension_report") or {}
    return [d["key"] for d in report.get("dimensions", [])]


def _decompose(run: RankingRun) -> dict | None:
    return (run.criteria or {}).get("decompose_audit")


def _match(run: RankingRun) -> dict | None:
    return (run.criteria or {}).get("match_audit")


def _fingerprint(run: RankingRun) -> str | None:
    return (run.criteria or {}).get("rank_inputs_fingerprint")


def main() -> None:
    db = SessionLocal()
    try:
        runs = list(db.scalars(select(RankingRun).order_by(RankingRun.id.asc())))
    finally:
        db.close()

    if not runs:
        print("No ranking runs found. Run Sync → Screen → Rank first.")
        return

    print(f"\n{'=' * 70}")
    print(f"LOCKED-POOL CONVERGENCE READOUT — {len(runs)} run(s)")
    print(f"{'=' * 70}\n")

    union: set[str] = set()
    prev_fingerprint: str | None = None

    for i, run in enumerate(runs, start=1):
        keys = _dim_keys(run)
        keyset = set(keys)
        fresh = keyset - union  # keys never seen in any earlier run
        union |= keyset

        fp = _fingerprint(run)
        pool_note = ""
        if prev_fingerprint is not None:
            # The fingerprint folds pool + prompts + models. Unchanged ⇒ the whole
            # rank-inputs set is identical, which for a locked pool means the pool
            # didn't move — so any dimension churn is pure discovery nondeterminism.
            pool_note = (
                "  (rank inputs UNCHANGED vs prior — churn is discovery nondeterminism)"
                if fp == prev_fingerprint
                else "  (rank inputs CHANGED vs prior)"
            )
        prev_fingerprint = fp

        print(f"── Run {i}  (id={run.id}){pool_note}")
        print(f"   dimensions this run : {len(keys)}")
        print(f"   new vs. prior union : {len(fresh)}  {sorted(fresh) if fresh else ''}")
        print(f"   cumulative union    : {len(union)}")

        dec = _decompose(run)
        if dec:
            # Decomposition settle-down: how many raw axes across the K fan-out reports
            # collapsed into the settled set, and how many of those settled axes are
            # merges. This replaced the reconcile readout when the fan-out redesign
            # removed reconcile.
            print(
                f"   decomposition       : {dec.get('input_dimension_count', 0)} input "
                f"→ {dec.get('settled_count', 0)} settled ({dec.get('merge_count', 0)} merges)"
            )
        else:
            print("   decomposition       : (none — run predates the fan-out redesign)")

        match = _match(run)
        if match:
            disc = len(match.get("raw_discovery_dimensions", []))
            matched = len(match.get("new_to_old", {}) or {})
            cf = f"{matched / disc:.0%}" if disc else "—"
            print(f"   match carry-forward : {matched}/{disc} discovered matched a prior (rate {cf})")
        print()

    # Convergence verdict heuristic: how many NEW keys did the last run add?
    print(f"{'=' * 70}")
    if len(runs) >= 2:
        last_keys = set(_dim_keys(runs[-1]))
        union_before_last: set[str] = set()
        for run in runs[:-1]:
            union_before_last |= set(_dim_keys(run))
        added_by_last = last_keys - union_before_last
        print(
            f"CONVERGENCE: the last run added {len(added_by_last)} key(s) not seen "
            f"in any prior run.\n  Trend to watch across runs: new-keys-per-run → 0 "
            f"means CONVERGING; steady/growing means CREEPING."
        )
        if added_by_last:
            print(f"  Last run's new keys: {sorted(added_by_last)}")
    else:
        print("CONVERGENCE: need ≥2 runs to judge. Re-rank the unchanged pool and re-run this.")
    print(f"  Total distinct keys ever seen across {len(runs)} run(s): {len(union)}")
    print(f"{'=' * 70}\n")

    # Overlap: the redundancy the creep produced, made measurable (Fan-Out Redesign
    # judge, O2). Correlates score vectors of the cumulative-union dimensions; the
    # count of flagged pairs is the "how much did creep re-carve the same axis?"
    # number the sequential chain could never see. Zero score rows ⇒ skip (a run
    # discovered but never scored).
    db = SessionLocal()
    try:
        vectors = load_score_vectors(db)
    finally:
        db.close()
    if vectors:
        rep = overlap_report(vectors, keys=sorted(union))
        print(f"{'=' * 70}")
        print(f"OVERLAP (redundancy judge, r ≥ {rep.threshold}): "
              f"{len(rep.overlaps)} pair(s) of the {rep.distinct_count} scored union "
              f"dimensions correlate — finest score {rep.finest_score:.1f}.")
        print("  A converged, non-overlapping set flags ~0; many pairs = re-carvings "
              "of the same axis. See `python -m scripts.dimension_overlap` for detail.")
        print(f"{'=' * 70}\n")


if __name__ == "__main__":
    main()
