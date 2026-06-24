"""Unit tests for the pure ranking domain (milestone 8).

No DB, no AI — hand-built scores in, ranked rows out. These pin the contract:
weight-normalized fit, confidence never folded in, relative pool-position bands,
and a deterministic stable order.
"""

from app.domain.ranking import (
    BANDS,
    CandidateScores,
    ScoredDimension,
    rank_candidates,
)


def candidate(app_id: int, **dim_scores: float) -> CandidateScores:
    """A candidate scored on the given dimensions. Confidence/grounding are
    filled with placeholders — the math only reads ``score``.
    """
    return CandidateScores(
        application_id=app_id,
        name=f"Applicant {app_id}",
        scores=[
            ScoredDimension(
                dimension_key=key,
                name=key.replace("_", " ").title(),
                score=score,
                confidence="low",
                rationale="",
                evidence="",
            )
            for key, score in dim_scores.items()
        ],
    )


EQUAL = {"a": 1.0, "b": 1.0}


def test_equal_weight_fit_is_plain_average() -> None:
    [row] = rank_candidates([candidate(1, a=0.8, b=0.2)], EQUAL)
    assert row.fit == 0.5


def test_orders_by_fit_descending_with_stable_tiebreak() -> None:
    candidates = [
        candidate(3, a=0.2, b=0.2),  # fit 0.2
        candidate(1, a=0.9, b=0.9),  # fit 0.9
        candidate(2, a=0.9, b=0.9),  # fit 0.9 — ties with id 1
    ]
    ranked = rank_candidates(candidates, EQUAL)
    # Higher fit first; equal fit broken by application_id ascending.
    assert [r.application_id for r in ranked] == [1, 2, 3]
    assert [r.rank for r in ranked] == [1, 2, 3]


def test_weights_change_the_order() -> None:
    candidates = [
        candidate(1, a=1.0, b=0.0),
        candidate(2, a=0.0, b=1.0),
    ]
    # Weighting b far above a flips who leads.
    ranked = rank_candidates(candidates, {"a": 0.1, "b": 0.9})
    assert ranked[0].application_id == 2


def test_zero_weight_dimension_is_excluded_from_fit() -> None:
    # b is weight 0, so fit depends only on a — but b is still kept as a
    # contribution for the explainable row.
    [row] = rank_candidates(
        [candidate(1, a=0.4, b=1.0)], {"a": 1.0, "b": 0.0}
    )
    assert row.fit == 0.4
    assert {c.dimension_key for c in row.contributions} == {"a", "b"}


def test_no_weight_at_all_yields_zero_fit() -> None:
    [row] = rank_candidates(
        [candidate(1, a=0.9, b=0.9)], {"a": 0.0, "b": 0.0}
    )
    assert row.fit == 0.0


def test_confidence_is_surfaced_not_folded_into_fit() -> None:
    # Two identical scores, different confidence, must produce identical fit:
    # confidence is display-only.
    high = CandidateScores(
        1, "High", [ScoredDimension("a", "A", 0.6, "high", "", "")]
    )
    low = CandidateScores(
        2, "Low", [ScoredDimension("a", "A", 0.6, "low", "", "")]
    )
    ranked = rank_candidates([high, low], {"a": 1.0})
    assert ranked[0].fit == ranked[1].fit == 0.6
    # And the label is preserved on the contribution.
    assert ranked[0].contributions[0].confidence == "high"


def test_bands_are_relative_to_the_pool() -> None:
    # Eight candidates with distinct, descending fit fall into the four bands two
    # at a time (relative position, not absolute thresholds).
    candidates = [candidate(i, a=1.0 - i * 0.1) for i in range(8)]
    ranked = rank_candidates(candidates, {"a": 1.0})
    assert [r.band for r in ranked] == [
        "Strong fit", "Strong fit",
        "Promising", "Promising",
        "Mixed", "Mixed",
        "Limited", "Limited",
    ]


def test_low_scores_still_get_a_top_band_when_they_lead_the_pool() -> None:
    # Bands are relative: even an all-weak pool has a "Strong fit" at the top.
    candidates = [candidate(1, a=0.2), candidate(2, a=0.1)]
    ranked = rank_candidates(candidates, {"a": 1.0})
    assert ranked[0].band == "Strong fit"
    assert ranked[0].fit == 0.2  # the number stays honest


def test_equal_fit_shares_a_band() -> None:
    # A tie straddling a band boundary must not split identical fit into two
    # different labels.
    candidates = [candidate(i, a=0.5) for i in range(4)]
    ranked = rank_candidates(candidates, {"a": 1.0})
    assert len({r.band for r in ranked}) == 1


def test_empty_pool_ranks_to_empty() -> None:
    assert rank_candidates([], EQUAL) == []


def test_band_labels_cover_exactly_the_declared_set() -> None:
    candidates = [candidate(i, a=1.0 - i * 0.05) for i in range(12)]
    ranked = rank_candidates(candidates, {"a": 1.0})
    assert {r.band for r in ranked} <= set(BANDS)
