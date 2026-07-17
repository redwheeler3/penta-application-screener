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
        dimensions=[
            PoolDimension(key=k, name=k, definition="d", high_end="high", low_end="low", why_it_differentiates="w")
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
    assert weights["a"] == 1.0  # one tier
    assert weights["b"] == 1.0
    assert weights["c"] == 0.0
    assert weights["d"] == 0.0


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
    assert weights["b"] == 0.0
    assert weights["c"] == 0.0
    assert weights["d"] == 0.0


def test_stale_key_in_layout_is_ignored() -> None:
    # A tier naming a dimension that no longer exists must not appear in the output;
    # only the requested keys are returned.
    layout = [tier("t1", ["a", "gone"])]
    weights = weights_from_tiers(["a"], layout)
    assert weights == {"a": 1.0}
    assert "gone" not in weights


# --- adopt_matched_keys: matched dims are replaced wholesale by their prior self ---


def test_adopt_replaces_matched_dim_with_prior_text() -> None:
    # A match reuses the prior dimension's CACHED SCORE, which was computed against
    # the prior definition. So the prior text must win over the fresh re-discovered
    # wording — otherwise the committee sees a score labelled with a definition it
    # was not scored against.
    new = PoolDimensionReport(
        dimensions=[
            PoolDimension(
                key="long_term_stability", name="Fresh Name",
                definition="fresh def", high_end="high", low_end="low", why_it_differentiates="fresh why",
            )
        ],
    )
    prior = PoolDimensionReport(
        dimensions=[
            PoolDimension(
                key="long_term_residency", name="Prior Name",
                definition="prior def", high_end="high", low_end="low", why_it_differentiates="prior why",
            )
        ],
    )
    adopted = adopt_matched_keys(new, {"long_term_stability": "long_term_residency"}, prior)
    dim = adopted.dimensions[0]
    assert dim.key == "long_term_residency"  # adopted the prior key (identity)
    assert dim.name == "Prior Name"  # AND the prior text (pairs with cached score)
    assert dim.definition == "prior def"
    assert dim.why_it_differentiates == "prior why"


def test_adopt_keeps_fresh_committee_flag_on_match() -> None:
    # from_committee_request is THIS run's provenance (did the committee ask for this
    # axis now?), not part of the scored concept — so it follows the fresh dim even
    # when the prior text is adopted, so a newly-requested match still auto-favourites.
    new = PoolDimensionReport(
        dimensions=[
            PoolDimension(
                key="fresh", name="n", definition="d", high_end="high", low_end="low", why_it_differentiates="w",
                from_committee_request=True,
            )
        ],
    )
    prior = report("prior")  # from_committee_request defaults False
    adopted = adopt_matched_keys(new, {"fresh": "prior"}, prior)
    assert adopted.dimensions[0].key == "prior"
    assert adopted.dimensions[0].from_committee_request is True


def test_adopt_leaves_unmatched_key_alone() -> None:
    # No prior history at all: nothing to adopt, fresh dim passes through unchanged.
    adopted = adopt_matched_keys(report("income_mix"), {}, None)
    assert [d.key for d in adopted.dimensions] == ["income_mix"]


def test_adopt_unmatched_keeps_fresh_text() -> None:
    # A match map entry whose target isn't in prior history is treated as unmatched
    # (defensive), so the fresh dimension is kept as discovered.
    new = PoolDimensionReport(
        dimensions=[
            PoolDimension(key="new_axis", name="Fresh", definition="fresh def",
                          high_end="high", low_end="low", why_it_differentiates="w")
        ],
    )
    adopted = adopt_matched_keys(new, {"new_axis": "not_in_history"}, report("other"))
    assert adopted.dimensions[0].key == "new_axis"
    assert adopted.dimensions[0].definition == "fresh def"


def test_adopt_collapses_two_new_onto_one_prior_key() -> None:
    # Two new dims both matching the SAME prior key are a prior axis re-carved into twins
    # this run: they COLLAPSE into one dimension under the prior key (reusing its cached
    # score), never survive as two (which would double-weight one concept) and never
    # duplicate the key (which would 500 on the cache's UNIQUE constraint).
    new = report("x", "y")
    adopted = adopt_matched_keys(new, {"x": "shared", "y": "shared"}, report("shared"))
    keys = [d.key for d in adopted.dimensions]
    assert keys == ["shared"]  # collapsed to one, no duplicate, no stray "y"


# --- carry_forward_layout: matched vs. new, and the prior-Ignored case ---
# (Runs AFTER adopt_matched_keys, so a matched dimension already shares the prior
# key; carry-forward is pure key equality against the prior key set.)


def placements_from(tiers: list[dict]) -> dict[str, str]:
    """Build a most_recent_tier_by_key map from working tiers, as tier_history would."""
    return {key: t["id"] for t in tiers for key in t.get("dimension_keys", [])}


def test_carry_forward_places_matches_and_flags_gap_dimensions() -> None:
    # Prior run: 'a' in the Critical tier (working), 'b' in Ignore. Both were in the
    # immediately-prior run's report (continuous in the committee's view); 'c' is a
    # gap dimension (absent from the prior run — new or revived).
    scaffold = [tier("tier-s", ["a"]), tier("tier-a", []), tier("tier-b", [])]
    new = report("a", "b", "c")

    layout, flagged_keys = carry_forward_layout(
        new_report=new,
        scaffold_tiers=scaffold,
        most_recent_tier_by_key=placements_from(scaffold),
        immediately_prior_keys={"a", "b"},
    )

    placed = {t["id"]: t["dimension_keys"] for t in layout}
    # 'a' carried into the Critical tier (its most-recent working placement).
    assert placed["tier-s"] == ["a"]
    # 'b' was last in Ignore -> left unplaced (ignore decision carried) ...
    all_placed = {k for keys in placed.values() for k in keys}
    assert "b" not in all_placed
    # ... and NOT flagged: it was present in the prior run, so continuous in view.
    assert "b" not in flagged_keys
    # Only the gap dimension (absent from the prior run) is flagged.
    assert flagged_keys == ["c"]


def test_carry_forward_prior_run_dimension_is_not_flagged() -> None:
    # A dimension present in the immediately-prior run (even if it was in Ignore) is
    # continuous in the committee's view, so never flagged — new OR revived.
    scaffold = [tier("tier-s", ["participation"]), tier("tier-a", []), tier("tier-b", [])]
    new = report("participation", "financial_admin")  # financial_admin was Ignored last run

    layout, flagged_keys = carry_forward_layout(
        new_report=new,
        scaffold_tiers=scaffold,
        most_recent_tier_by_key=placements_from(scaffold),
        immediately_prior_keys={"participation", "financial_admin"},
    )
    assert flagged_keys == []  # both in the prior run; neither is a gap
    placed = {t["id"]: t["dimension_keys"] for t in layout}
    assert placed["tier-s"] == ["participation"]
    assert "financial_admin" not in {k for keys in placed.values() for k in keys}


def test_carry_forward_restores_placement_and_flags_revived() -> None:
    # The revival case: a dimension placed Critical several runs ago, gone since (absent
    # from the immediately-prior run), re-surfaces now. It restores to Critical (durable
    # committee intent spanning the gap) AND is flagged — a presence gap the committee
    # should see (the "Revived" label is derived separately from history).
    scaffold = [tier("tier-s", []), tier("tier-a", ["participation"]), tier("tier-b", [])]
    new = report("participation", "financial_stability")

    layout, flagged_keys = carry_forward_layout(
        new_report=new,
        scaffold_tiers=scaffold,
        # 'financial_stability' was last placed Critical (an older run); 'participation'
        # is in the current Important tier.
        most_recent_tier_by_key={"participation": "tier-a", "financial_stability": "tier-s"},
        # 'financial_stability' is NOT in the immediately-prior run (gone since) -> flagged;
        # 'participation' is -> not flagged.
        immediately_prior_keys={"participation"},
    )
    placed = {t["id"]: t["dimension_keys"] for t in layout}
    assert placed["tier-s"] == ["financial_stability"]  # restored to Critical
    assert placed["tier-a"] == ["participation"]
    assert flagged_keys == ["financial_stability"]  # gap -> flagged (revived)


def test_carry_forward_first_run_has_no_matches_and_no_flags() -> None:
    # No prior tiers (first run): default empty working tiers, nothing flagged.
    layout, flagged_keys = carry_forward_layout(
        new_report=report("x", "y"),
        scaffold_tiers=[],
        most_recent_tier_by_key={},
        immediately_prior_keys=set(),
    )
    assert flagged_keys == []
    assert all(t["dimension_keys"] == [] for t in layout)
