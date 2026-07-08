"""Unit tests for the pure tier->weights derivation (milestone 9).

No DB — hand-built tier layouts in, weight maps out. These pin the contract that
the tier-list UI and the ranking engine both depend on.

The layout holds only *working* tiers (most→least important). "Ignored" is the
absence of a placement, not a stored tier — a dimension in no tier has weight 0.
"""

from app.ai.schemas import PoolDimension, PoolDimensionReport
from app.services.ranking_run import (
    adopt_matched_keys,
    carry_forward_layout,
    weights_from_tiers,
)

KEYS = ["a", "b", "c", "d"]


def report(*keys: str) -> PoolDimensionReport:
    return PoolDimensionReport(
        summary="s",
        dimensions=[
            PoolDimension(key=k, name=k, definition="d", why_it_differentiates="w")
            for k in keys
        ],
    )


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
    # The opening default: Critical/Important/Minor exist but are empty, so nothing is placed. No
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


# --- adopt_matched_keys: rewrite matched dimensions to the prior key ---


def test_adopt_rewrites_matched_key_keeps_new_content() -> None:
    new = PoolDimensionReport(
        summary="s",
        dimensions=[
            PoolDimension(
                key="long_term_stability", name="Stability",
                definition="fresh def", why_it_differentiates="fresh why",
            )
        ],
    )
    adopted = adopt_matched_keys(new, {"long_term_stability": "long_term_residency"})
    dim = adopted.dimensions[0]
    assert dim.key == "long_term_residency"  # adopted the prior key (identity)
    assert dim.name == "Stability"  # but kept the new content
    assert dim.definition == "fresh def"


def test_adopt_leaves_unmatched_key_alone() -> None:
    adopted = adopt_matched_keys(report("income_mix"), {})
    assert [d.key for d in adopted.dimensions] == ["income_mix"]


def test_adopt_never_creates_a_duplicate_key() -> None:
    # If two new dims would both adopt the same prior key (or an adopted key
    # collides with another dim's untouched key), the second keeps its own key.
    new = report("x", "y")
    adopted = adopt_matched_keys(new, {"x": "shared", "y": "shared"})
    keys = [d.key for d in adopted.dimensions]
    assert keys[0] == "shared"
    assert keys[1] == "y"  # could not also be "shared" — kept its own
    assert len(set(keys)) == 2  # no duplicates


# --- carry_forward_layout: matched vs. new, and the prior-Ignored case ---
# (Runs AFTER adopt_matched_keys, so a matched dimension already shares the prior
# key; carry-forward is pure key equality against the prior key set.)


def placements_from(tiers: list[dict]) -> dict[str, str]:
    """Build a most_recent_tier_by_key map from working tiers, as tier_history would."""
    return {key: t["id"] for t in tiers for key in t.get("dimension_keys", [])}


def test_carry_forward_places_matches_and_flags_only_genuinely_new() -> None:
    # Prior history: 'a' in the Critical tier (working), 'b' in Ignore (absent from
    # the placement map). Both keys are known; 'c' is genuinely new (never seen).
    scaffold = [tier("tier-s", ["a"]), tier("tier-a", []), tier("tier-b", [])]
    new = report("a", "b", "c")

    layout, new_keys = carry_forward_layout(
        new_report=new,
        scaffold_tiers=scaffold,
        most_recent_tier_by_key=placements_from(scaffold),
        known_keys={"a", "b"},
    )

    placed = {t["id"]: t["dimension_keys"] for t in layout}
    # 'a' carried into the Critical tier (its most-recent working placement).
    assert placed["tier-s"] == ["a"]
    # 'b' was last in Ignore -> left unplaced (ignore decision carried) ...
    all_placed = {k for keys in placed.values() for k in keys}
    assert "b" not in all_placed
    # ... and crucially NOT flagged new: the committee already weighed in on it.
    assert "b" not in new_keys
    # Only the genuinely-new dimension is flagged.
    assert new_keys == ["c"]


def test_carry_forward_prior_ignored_dimension_is_not_new() -> None:
    # Regression: a dimension that was in Ignore must never be flagged "new".
    scaffold = [tier("tier-s", ["participation"]), tier("tier-a", []), tier("tier-b", [])]
    new = report("participation", "financial_admin")  # financial_admin was Ignored before

    layout, new_keys = carry_forward_layout(
        new_report=new,
        scaffold_tiers=scaffold,
        most_recent_tier_by_key=placements_from(scaffold),
        known_keys={"participation", "financial_admin"},
    )
    assert new_keys == []  # both known; neither is new
    placed = {t["id"]: t["dimension_keys"] for t in layout}
    assert placed["tier-s"] == ["participation"]
    assert "financial_admin" not in {k for keys in placed.values() for k in keys}


def test_carry_forward_restores_placement_from_an_older_run() -> None:
    # The resurrection case A fixes: a dimension placed Critical several runs ago, gone
    # since, re-surfaces now. It must restore to Critical and NOT be flagged new — its
    # placement is durable committee intent that spanned the gap. (tier_history supplies
    # the most-recent placement + known keys across ALL runs; here we simulate that: the
    # current scaffold no longer lists 'financial_stability', but history remembers it.)
    scaffold = [tier("tier-s", []), tier("tier-a", ["participation"]), tier("tier-b", [])]
    new = report("participation", "financial_stability")

    layout, new_keys = carry_forward_layout(
        new_report=new,
        scaffold_tiers=scaffold,
        # 'financial_stability' was last placed Critical (an older run); 'participation'
        # is in the current Important tier.
        most_recent_tier_by_key={"participation": "tier-a", "financial_stability": "tier-s"},
        known_keys={"participation", "financial_stability"},
    )
    placed = {t["id"]: t["dimension_keys"] for t in layout}
    assert placed["tier-s"] == ["financial_stability"]  # restored to Critical
    assert placed["tier-a"] == ["participation"]
    assert new_keys == []  # seen before -> never flagged new


def test_carry_forward_first_run_has_no_matches_and_no_flags() -> None:
    # No prior tiers (first run): default empty working tiers, nothing flagged new.
    layout, new_keys = carry_forward_layout(
        new_report=report("x", "y"),
        scaffold_tiers=[],
        most_recent_tier_by_key={},
        known_keys=set(),
    )
    assert new_keys == []
    assert all(t["dimension_keys"] == [] for t in layout)
