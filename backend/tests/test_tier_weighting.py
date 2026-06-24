"""Unit tests for the pure tier->weights derivation (milestone 9).

No DB — hand-built tier layouts in, weight maps out. These pin the contract that
the tier-list UI and the ranking engine both depend on.
"""

from app.services.screening_run import weights_from_tiers

KEYS = ["a", "b", "c", "d"]


def tier(tier_id: str, keys: list[str], *, ignore: bool = False) -> dict:
    return {"id": tier_id, "label": tier_id, "dimension_keys": keys, "ignore": ignore}


def test_single_tier_is_equal_weight_baseline() -> None:
    # One working tier with everything = the M8 equal-weight baseline.
    layout = [tier("t1", KEYS), tier("ignore", [], ignore=True)]
    assert weights_from_tiers(KEYS, layout) == {"a": 1.0, "b": 1.0, "c": 1.0, "d": 1.0}


def test_descending_tiers_give_descending_weights() -> None:
    layout = [
        tier("t1", ["a"]),
        tier("t2", ["b"]),
        tier("t3", ["c", "d"]),  # equal within a tier
        tier("ignore", [], ignore=True),
    ]
    # Three non-ignore tiers: top=3, next=2, last=1.
    assert weights_from_tiers(KEYS, layout) == {"a": 3.0, "b": 2.0, "c": 1.0, "d": 1.0}


def test_ignore_tier_is_zero() -> None:
    layout = [
        tier("t1", ["a", "b"]),
        tier("ignore", ["c", "d"], ignore=True),
    ]
    weights = weights_from_tiers(KEYS, layout)
    assert weights["a"] == 1.0 and weights["b"] == 1.0  # one non-ignore tier
    assert weights["c"] == 0.0 and weights["d"] == 0.0


def test_unplaced_key_falls_back_to_top_weight() -> None:
    # 'd' is in no tier (e.g. just added). It should still count, at the top weight,
    # rather than silently dropping to 0.
    layout = [
        tier("t1", ["a"]),
        tier("t2", ["b", "c"]),
        tier("ignore", [], ignore=True),
    ]
    weights = weights_from_tiers(KEYS, layout)
    assert weights["d"] == 2.0  # two non-ignore tiers -> top weight 2


def test_no_non_ignore_tiers_falls_back_to_uniform() -> None:
    # Everything ignored would zero out fit entirely; guard with uniform 1.0 so the
    # ranking still has something to sort on.
    layout = [tier("ignore", KEYS, ignore=True)]
    assert weights_from_tiers(KEYS, layout) == {"a": 1.0, "b": 1.0, "c": 1.0, "d": 1.0}


def test_stale_key_in_layout_is_ignored() -> None:
    # A tier naming a dimension that no longer exists must not appear in the output;
    # only the requested keys are returned.
    layout = [tier("t1", ["a", "gone"]), tier("ignore", [], ignore=True)]
    weights = weights_from_tiers(["a"], layout)
    assert weights == {"a": 1.0}
    assert "gone" not in weights


def test_empty_layout_defaults_all_uniform() -> None:
    assert weights_from_tiers(KEYS, []) == {"a": 1.0, "b": 1.0, "c": 1.0, "d": 1.0}
