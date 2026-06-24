"""Deterministic ranking (milestone 8): turn per-candidate dimension scores into
a ranked shortlist.

This is pure math — no DB, no AI, no I/O — so it sits alongside ``hard_filters``
as deterministic domain logic, separate from AI-assisted evaluation (per the
engineering rules), and is trivially unit-testable with hand-built scores.

The contract (SPEC "Deterministic Ranked List"):

- **Fit** is the weight-normalized average of a candidate's per-dimension scores:
  ``Σ(weight·score) / Σ(weight)`` over dimensions whose weight is > 0. At M8 every
  weight is equal, so fit is a plain average; M9's narrowing answers are the only
  thing that moves weights off equal.
- **Confidence is surfaced, never folded into fit.** Each contribution keeps its
  confidence label for display, but a score moves the ranking by exactly its
  weight and nothing else — so the order stays explainable top-down.
- **Bands are relative to THIS pool**, not absolute thresholds: a candidate's
  label comes from its position in the ranking (rank percentile), so the bands
  always spread the pool and recompute as weights change. Equal-fit candidates
  always share a band.

The LLM never produces the order; it produced the scores, and this is arithmetic
on top of them.
"""

from __future__ import annotations

from dataclasses import dataclass

# Relative band labels, strongest first. A candidate's band is chosen by its
# position in the ranking, split into these even slices of the pool.
BANDS = ("Strong fit", "Promising", "Mixed", "Limited")


@dataclass(frozen=True)
class ScoredDimension:
    """One candidate's score on one dimension, as the ranker consumes it. A flat
    view of ``DimensionScore`` joined to its dimension label — no Pydantic or DB
    types, so the ranking function stays pure and easy to test.
    """

    dimension_key: str
    name: str
    score: float
    confidence: str
    rationale: str
    evidence: str


@dataclass(frozen=True)
class CandidateScores:
    """Everything the ranker needs about one candidate: identity plus its scores
    against the run's dimensions.
    """

    application_id: int
    name: str | None
    scores: list[ScoredDimension]


@dataclass(frozen=True)
class DimensionContribution:
    """How one dimension fed a candidate's fit — score and the weight applied,
    plus the grounding kept for the explainable per-row view.
    """

    dimension_key: str
    name: str
    score: float
    weight: float
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
    above_line: bool  # within the current shortlist line
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
    """Relative band from rank position: the pool is split into even contiguous
    slices, one per label, top-down. ``rank`` is 1-based.

    Anchored at the top (``(rank - 1) / total``) so rank 1 is always in the top
    band — for a small pool that can't fill every slice, the leader still reads as
    the strongest fit rather than landing mid-table on a boundary.
    """
    if total <= 0:
        return BANDS[-1]
    position = (rank - 1) / total  # 0 at the top of the list, <1 at the bottom
    index = min(int(position * len(BANDS)), len(BANDS) - 1)
    return BANDS[index]


def _contributions(
    scores: list[ScoredDimension], weights: dict[str, float]
) -> list[DimensionContribution]:
    """All of a candidate's scored dimensions, with the weight applied. Every
    dimension is kept (even weight 0) so the row explains the full picture; only
    the fit math skips weight-0 dimensions.
    """
    return [
        DimensionContribution(
            dimension_key=s.dimension_key,
            name=s.name,
            score=s.score,
            weight=weights.get(s.dimension_key, 0.0),
            confidence=s.confidence,
            rationale=s.rationale,
            evidence=s.evidence,
        )
        for s in scores
    ]


def rank_candidates(
    candidates: list[CandidateScores],
    weights: dict[str, float],
    shortlist_size: int,
) -> list[RankedCandidate]:
    """Rank the pool by fit (descending) and assign relative bands.

    Deterministic and stable: ties in fit are broken by ``application_id`` so the
    same inputs always produce the same order. Equal-fit candidates are assigned
    the same band (the band of the first of the tie) so identical fit never lands
    in different labels.
    """
    ordered = sorted(
        candidates,
        key=lambda c: (-_fit(c.scores, weights), c.application_id),
    )

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
                above_line=rank <= shortlist_size,
                contributions=_contributions(candidate.scores, weights),
            )
        )
        prev_fit = fit
        prev_band = band
    return ranked
