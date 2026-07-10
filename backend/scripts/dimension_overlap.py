"""Overlap metric for the Fan-Out Redesign bake-off (SPEC "Fan-Out Redesign" O2).

Read-only. The judge that scores a *decomposition* — a settled set of dimensions —
on the "finest stable non-overlapping set" target. It answers, from data already on
disk (no model call), the one question the sequential chain could never ask: **are
any two surviving dimensions really the same axis re-carved?**

The proxy (why this is not circular): the real overlap test — "would these two
definitions score the same applicant the same way?" — needs the model, but the
metric must NOT consult the same model it judges, or it grades its own homework.
Instead it reads the per-(candidate, dimension) 0..1 scores the app already
persists (``ApplicationAIResult.output["score"]``, kind ``dimension_scoring:<key>``)
and asks a deterministic question of them: do two dimensions' **score vectors
across the pool correlate**? Two carvings of one concept move together candidate
by candidate (high Pearson r); two genuinely distinct axes need not. High r is a
*flag to inspect*, not an automatic verdict — a pair can correlate for a real
reason (two distinct skills both tracking "high-agency applicant") — but on a
creeping set it reliably surfaces the re-carvings we diagnosed by hand.

Timing note (see O2): score vectors exist only *after* scoring, and the fan-out
scores once against the already-settled set — so this is an OFFLINE judge
(decompose → score → measure), never an inline signal a Merger consults mid-run.

Usage (standalone, prints the overlap report for every dimension ever scored):

    cd backend && uv run python -m scripts.dimension_overlap

Or import ``overlap_report`` / ``finest_score`` to score a specific dimension set
in the bake-off harness.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt

from sqlalchemy import select

from app.ai.dimension_scoring import KIND_PREFIX
from app.db.models import ApplicationAIResult
from app.db.session import SessionLocal

# Default correlation threshold above which a surviving pair is flagged as a
# suspected un-merged overlap. O2 started at 0.9; validated down to 0.85 on the
# 10-run pool — that cut flags the 2 genuine duplicates (r≈0.85-0.89, e.g.
# governance_body_experience ↔ depth_of_shared_governance_experience) and nothing
# spurious, while 0.75 drags in real confounds (engaged applicants are both willing
# AND available → correlated but distinct). A flag is a prompt to inspect, not an
# auto-merge; definitions stay the ground truth. Still a tunable knob.
DEFAULT_OVERLAP_THRESHOLD = 0.85

# Penalty per flagged overlapping pair when scoring a set's "finest"-ness. One
# overlap cancels roughly one axis's worth of credit, so a set that pads its count
# with re-carvings scores no better than the smaller clean set it should have been.
DEFAULT_OVERLAP_PENALTY = 1.0


@dataclass(frozen=True)
class OverlapPair:
    """One dimension pair and how correlated their pool score vectors are."""

    key_a: str
    key_b: str
    r: float
    n: int  # candidates scored on BOTH (the correlation's support)


@dataclass(frozen=True)
class OverlapReport:
    """The judge's verdict on one dimension set."""

    keys: list[str]
    distinct_count: int
    overlaps: list[OverlapPair]  # pairs at/above the threshold, worst r first
    threshold: float
    penalty: float

    @property
    def finest_score(self) -> float:
        """Higher is better: reward distinct axes, penalize each un-merged overlap.

        ``distinct_count − penalty × overlaps``. A creeping set (many axes, many
        overlapping) is docked on both terms at once; a clean, finely-factored set
        scores near its raw count. Directional, not just pass/fail (see O2).
        """
        return self.distinct_count - self.penalty * len(self.overlaps)


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    """Pearson correlation of two equal-length vectors, or None when undefined.

    None when fewer than 2 points or either vector is constant (zero variance) —
    a flat axis has no correlation to speak of, so it simply isn't flagged (the
    right behaviour: a flat axis moves no ranking, overlap or not).
    """
    n = len(xs)
    if n < 2:
        return None
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    dx = [x - mean_x for x in xs]
    dy = [y - mean_y for y in ys]
    cov = sum(a * b for a, b in zip(dx, dy))
    var_x = sum(a * a for a in dx)
    var_y = sum(b * b for b in dy)
    if var_x == 0.0 or var_y == 0.0:
        return None
    return cov / sqrt(var_x * var_y)


def load_score_vectors(db) -> dict[str, dict[int, float]]:
    """Every dimension key ever scored → {application_id: latest score}.

    Reads all ``dimension_scoring:<key>`` rows and keeps the newest per
    (key, candidate) by ``created_at`` — the same "a re-score supersedes older
    rows" rule the ranker uses (see ``ranking_view.candidate_scores``), so the
    metric measures the scores the committee actually ranks on.
    """
    rows = db.scalars(
        select(ApplicationAIResult)
        .where(ApplicationAIResult.kind.like(f"{KIND_PREFIX}:%"))
        .order_by(ApplicationAIResult.created_at)
    )
    vectors: dict[str, dict[int, float]] = {}
    for row in rows:
        key = row.kind.split(":", 1)[1]  # strip the "dimension_scoring:" prefix
        score = float((row.output or {}).get("score", 0.0))
        vectors.setdefault(key, {})[row.application_id] = score  # later row wins
    return vectors


def overlap_report(
    vectors: dict[str, dict[int, float]],
    keys: list[str] | None = None,
    *,
    threshold: float = DEFAULT_OVERLAP_THRESHOLD,
    penalty: float = DEFAULT_OVERLAP_PENALTY,
    min_support: int = 3,
) -> OverlapReport:
    """Score a dimension set: flag every pair whose pool score vectors correlate
    at/above ``threshold`` (computed over the candidates scored on BOTH; needs at
    least ``min_support`` shared candidates to be meaningful).

    ``keys`` restricts the scored set (e.g. one run's dimensions, or a proposed
    decomposition); None means every key present in ``vectors``. Keys with no score
    vector are dropped from the count — you can only judge overlap on scored axes.
    """
    present = [k for k in (keys if keys is not None else vectors) if k in vectors]
    overlaps: list[OverlapPair] = []
    for i, key_a in enumerate(present):
        for key_b in present[i + 1 :]:
            va, vb = vectors[key_a], vectors[key_b]
            common = sorted(va.keys() & vb.keys())
            if len(common) < min_support:
                continue
            r = _pearson([va[c] for c in common], [vb[c] for c in common])
            if r is not None and r >= threshold:
                overlaps.append(OverlapPair(key_a, key_b, r, len(common)))
    overlaps.sort(key=lambda p: p.r, reverse=True)
    return OverlapReport(
        keys=present,
        distinct_count=len(present),
        overlaps=overlaps,
        threshold=threshold,
        penalty=penalty,
    )


def main() -> None:
    db = SessionLocal()
    try:
        vectors = load_score_vectors(db)
    finally:
        db.close()

    if not vectors:
        print("No dimension_scoring rows found. Run Sync → Screen → Rank first.")
        return

    report = overlap_report(vectors)
    print(f"\n{'=' * 70}")
    print("DIMENSION OVERLAP READOUT — every dimension ever scored")
    print(f"{'=' * 70}")
    print(f"  distinct scored dimensions : {report.distinct_count}")
    print(f"  overlap threshold (r ≥)    : {report.threshold}")
    print(f"  flagged overlapping pairs  : {len(report.overlaps)}")
    print(f"  finest score               : {report.finest_score:.1f}"
          f"  (= {report.distinct_count} - {report.penalty:g} * {len(report.overlaps)})")
    print(f"{'=' * 70}\n")
    if report.overlaps:
        print("Suspected un-merged overlaps (worst first — inspect, don't auto-merge):")
        for p in report.overlaps:
            print(f"  r={p.r:+.3f}  (n={p.n})  {p.key_a}  ↔  {p.key_b}")
    else:
        print("No pairs above threshold — the set reads as non-overlapping.")
    print()


if __name__ == "__main__":
    main()
