"""Unit tests for the pure tier->weights derivation (milestone 9).

No DB — hand-built tier layouts in, weight maps out. These pin the contract that
the tier-list UI and the ranking engine both depend on.

The layout holds only *working* tiers (most→least important). "Ignored" is the
absence of a placement, not a stored tier — a dimension in no tier has weight 0.
"""

from app.services.screening_run import weights_from_tiers

KEYS = ["a", "b", "c", "d"]


def tier(tier_id: str, keys: list[str]) -> dict:
    return {"id": tier_id, "label": tier_id, "dimension_keys": keys}


def test_single_tier_is_equal_weight_baseline() -> None:
    # One working tier with everything = the M8 equal-weight baseline.
    layout = [tier("t1", KEYS)]
    assert weights_from_tiers(KEYS, layout) == {"a": 1.0, "b": 1.0, "c": 1.0, "d": 1.0}


def test_descending_tiers_give_descending_weights() -> None:
    layout = [
        tier("t1", ["a"]),
        tier("t2", ["b"]),
        tier("t3", ["c", "d"]),  # equal within a tier
    ]
    # Three tiers: top=3, next=2, last=1.
    assert weights_from_tiers(KEYS, layout) == {"a": 3.0, "b": 2.0, "c": 1.0, "d": 1.0}


def test_unplaced_keys_are_zero() -> None:
    # 'c' and 'd' are in no working tier -> ignored by absence -> weight 0.
    layout = [tier("t1", ["a", "b"])]
    weights = weights_from_tiers(KEYS, layout)
    assert weights["a"] == 1.0 and weights["b"] == 1.0  # one tier
    assert weights["c"] == 0.0 and weights["d"] == 0.0


def test_no_tiers_falls_back_to_uniform() -> None:
    # An empty board (everything ignored by absence) would zero out fit entirely;
    # guard with uniform 1.0 so the opening ranking is the equal-weight baseline.
    assert weights_from_tiers(KEYS, []) == {"a": 1.0, "b": 1.0, "c": 1.0, "d": 1.0}


def test_empty_working_tiers_fall_back_to_uniform() -> None:
    # The opening default: S/A/B exist but are empty, so nothing is placed. No
    # dimension carries positive weight -> uniform baseline, not an all-zero collapse.
    layout = [tier("tier-s", []), tier("tier-a", []), tier("tier-b", [])]
    assert weights_from_tiers(KEYS, layout) == {"a": 1.0, "b": 1.0, "c": 1.0, "d": 1.0}


def test_one_placed_dimension_is_not_uniform() -> None:
    # As soon as the committee drags one dimension into a tier, the board is no
    # longer empty: that dimension gets positive weight, the unplaced rest stay 0.
    layout = [tier("tier-s", ["a"]), tier("tier-a", []), tier("tier-b", [])]
    weights = weights_from_tiers(KEYS, layout)
    assert weights["a"] == 3.0  # three working tiers -> top weight 3
    assert weights["b"] == 0.0 and weights["c"] == 0.0 and weights["d"] == 0.0


def test_stale_key_in_layout_is_ignored() -> None:
    # A tier naming a dimension that no longer exists must not appear in the output;
    # only the requested keys are returned.
    layout = [tier("t1", ["a", "gone"])]
    weights = weights_from_tiers(["a"], layout)
    assert weights == {"a": 1.0}
    assert "gone" not in weights
