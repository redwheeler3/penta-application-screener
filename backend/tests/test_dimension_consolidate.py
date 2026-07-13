"""Unit tests for the deterministic nominate stage of post-score consolidation.

``nominate_pairs`` flags correlated pairs for the LLM confirm. The subtle contract it
must hold: only LIVE keys (present in ``canonical_rank``, i.e. some current dimension
report) may be nominated. ``load_score_vectors`` retains score rows for keys already
merged away, and those still correlate with their own survivor — nominating them would
re-merge a dead key with no definition to judge (a phantom merge). ``canonical_rank``
membership is the live-key gate.
"""

from app.ai.dimension_consolidate import nominate_pairs

# Two candidates scored identically → r = 1.0, well above any threshold.
_SAME = {1: 0.1, 2: 0.5, 3: 0.9, 4: 0.3}


def test_nominates_a_correlated_live_pair() -> None:
    vectors = {"new_axis": _SAME, "prior_axis": _SAME}
    rank = {"prior_axis": 1, "new_axis": 2}  # both live; prior is older
    pairs = nominate_pairs(["new_axis"], rank, vectors, threshold=0.85)
    assert len(pairs) == 1
    # Older key kept, newer dropped.
    assert (pairs[0].keep, pairs[0].drop) == ("prior_axis", "new_axis")


def test_does_not_nominate_a_dead_key_with_a_lingering_vector() -> None:
    # `pet_ownership` was merged away on an earlier run: its score rows persist (so it's
    # in `vectors`) but it's absent from `canonical_rank` (gone from every live report).
    # It correlates perfectly with its survivor `pet_load`, but must NOT be nominated —
    # re-merging a dead key with no definition is the phantom-merge bug this guards.
    vectors = {"pet_load": _SAME, "pet_ownership": _SAME}
    rank = {"pet_load": 2}  # pet_ownership deliberately absent (dead)
    pairs = nominate_pairs(["pet_load"], rank, vectors, threshold=0.85)
    assert pairs == []


def test_skips_a_run_key_absent_from_canonical_rank() -> None:
    # Defensive: a run key with no rank (shouldn't happen — the run is persisted before
    # key_history reads it) is skipped, not crashed on.
    vectors = {"a": _SAME, "b": _SAME}
    pairs = nominate_pairs(["a"], {"b": 1}, vectors, threshold=0.85)  # "a" unranked
    assert pairs == []
