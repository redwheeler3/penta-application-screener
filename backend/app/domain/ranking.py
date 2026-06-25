"""Deterministic ranking: turn per-candidate dimension scores into a ranked
shortlist.

Pure math — no DB, AI, or I/O — so it sits alongside ``hard_filters`` as
deterministic domain logic, trivially unit-testable. The contract (SPEC
"Deterministic Ranked List"):

- **Fit** is the weight-normalized average of a candidate's per-dimension scores,
  ``Σ(weight·score) / Σ(weight)`` over dimensions whose weight is > 0.
- **Confidence is surfaced, never folded into fit** — a score moves the ranking by
  exactly its weight, so the order stays explainable top-down.
- **Bands are relative to THIS pool**, not absolute thresholds: a candidate's label
  comes from its rank position, recomputed as weights change. Equal-fit candidates
  share a band.

The LLM produced the scores; this is arithmetic on top of them.
"""

from __future__ import annotations

from dataclasses import dataclass

# Relative band labels, strongest first. A candidate's band is chosen by its
# position in the ranking, split into these even slices of the pool.
BANDS = ("Strong fit", "Promising", "Mixed", "Limited")


@dataclass(frozen=True)
class ScoredDimension:
    """One candidate's score on one dimension — a flat view of ``DimensionScore``
    joined to its label, free of Pydantic/DB types so the ranker stays pure.
    """

    dimension_key: str
    name: str
    score: float
    confidence: str
    rationale: str
    evidence: str


@dataclass(frozen=True)
class CandidateScores:
    """One candidate's identity plus its scores against the run's dimensions."""

    application_id: int
    name: str | None
    scores: list[ScoredDimension]


@dataclass(frozen=True)
class DimensionContribution:
    """How one dimension fed a candidate's fit — score, weight, and grounding.

    ``impact = weight · (score − pool_mean)`` is the dimension's signed contribution
    to how far this candidate sits from the pool average (the per-dimension
    decomposition of ``fit_i − avg_fit``). Ranking contributions by ``abs(impact)``
    surfaces what actually moved this candidate: a heavy dimension everyone scores
    alike has near-zero impact, while a big strike (low score on a heavy dimension)
    ranks high and negative. Sign carries direction; magnitude carries importance.
    """

    dimension_key: str
    name: str
    score: float
    weight: float
    impact: float
    confidence: str
    rationale: str
    evidence: str


@dataclass(frozen=True)
class RankedCandidate:
    application_id: int
    name: str | None
    rank: int  # 1-based position in the ranking
    fit: float  # 0..1 weighted average; supporting detail, not the headline
    band: str  # relative pool-position label (see BANDS)
    contributions: list[DimensionContribution]


def _fit(scores: list[ScoredDimension], weights: dict[str, float]) -> float:
    """Weight-normalized average over dimensions with positive weight. Returns
    0.0 when no dimension carries weight (nothing to rank on yet).
    """
    weighted_sum = 0.0
    total_weight = 0.0
    for s in scores:
        weight = weights.get(s.dimension_key, 0.0)
        if weight <= 0.0:
            continue
        weighted_sum += weight * s.score
        total_weight += weight
    if total_weight == 0.0:
        return 0.0
    return weighted_sum / total_weight


def _band_for(rank: int, total: int) -> str:
    """Relative band from 1-based rank position: the pool split into even slices,
    one per label, top-down. Anchored at the top so rank 1 is always the top band
    even when a small pool can't fill every slice.
    """
    if total <= 0:
        return BANDS[-1]
    position = (rank - 1) / total  # 0 at the top of the list, <1 at the bottom
    index = min(int(position * len(BANDS)), len(BANDS) - 1)
    return BANDS[index]


def _pool_means(candidates: list[CandidateScores]) -> dict[str, float]:
    """Mean score per dimension across the pool — the baseline each candidate's
    impact is measured against. Averaged only over candidates that have the
    dimension scored, so a missing dimension doesn't drag the mean toward zero.
    """
    totals: dict[str, float] = {}
    counts: dict[str, int] = {}
    for candidate in candidates:
        for s in candidate.scores:
            totals[s.dimension_key] = totals.get(s.dimension_key, 0.0) + s.score
            counts[s.dimension_key] = counts.get(s.dimension_key, 0) + 1
    return {key: totals[key] / counts[key] for key in totals}


def _contributions(
    scores: list[ScoredDimension],
    weights: dict[str, float],
    means: dict[str, float],
) -> list[DimensionContribution]:
    """A candidate's scored dimensions with weight and pool-relative impact. Every
    dimension is kept (even weight 0) for the explainable row; only the fit math
    skips weight-0 dimensions.
    """
    return [
        DimensionContribution(
            dimension_key=s.dimension_key,
            name=s.name,
            score=s.score,
            weight=weights.get(s.dimension_key, 0.0),
            impact=weights.get(s.dimension_key, 0.0)
            * (s.score - means.get(s.dimension_key, s.score)),
            confidence=s.confidence,
            rationale=s.rationale,
            evidence=s.evidence,
        )
        for s in scores
    ]


def rank_candidates(
    candidates: list[CandidateScores],
    weights: dict[str, float],
) -> list[RankedCandidate]:
    """Rank the pool by fit (descending) and assign relative bands.

    Deterministic and stable: fit ties break by ``application_id``, and equal-fit
    candidates share the band of the first of the tie so identical fit never lands
    in different labels.
    """
    ordered = sorted(
        candidates,
        key=lambda c: (-_fit(c.scores, weights), c.application_id),
    )

    means = _pool_means(candidates)
    total = len(ordered)
    ranked: list[RankedCandidate] = []
    prev_fit: float | None = None
    prev_band: str | None = None
    for index, candidate in enumerate(ordered):
        rank = index + 1
        fit = _fit(candidate.scores, weights)
        # Equal fit shares a band; otherwise band follows rank position.
        if prev_band is not None and prev_fit is not None and fit == prev_fit:
            band = prev_band
        else:
            band = _band_for(rank, total)
        ranked.append(
            RankedCandidate(
                application_id=candidate.application_id,
                name=candidate.name,
                rank=rank,
                fit=fit,
                band=band,
                contributions=_contributions(candidate.scores, weights, means),
            )
        )
        prev_fit = fit
        prev_band = band
    return ranked
