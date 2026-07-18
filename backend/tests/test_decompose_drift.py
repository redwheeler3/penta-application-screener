"""The Tier-1 decompose-drift detector: prose names a key that routed into a different axis."""

from scripts.decompose_drift import find_drift


def test_flags_a_belongs_here_key_that_routed_elsewhere() -> None:
    # The golden-case-#2 shape: axis A's decision CLAIMS it folds in a key, but that key
    # actually routed into a different axis.
    settled = [
        {"key": "skill_axis", "source_keys": ["skill_axis"],
         "decision": "commitment_key measures the same skill and is folded in here."},
        {"key": "participation_axis", "source_keys": ["participation_axis", "commitment_key"],
         "decision": "Stated commitment to co-op duties."},
    ]
    drift = find_drift(settled)
    named = {(c.axis_key, c.named_key, c.routed_to) for c in drift}
    # skill_axis's decision says commitment_key is 'folded in here', but it routed into
    # participation_axis → drift.
    assert ("skill_axis", "commitment_key", "participation_axis") in named


def test_distinct_from_reference_is_not_flagged() -> None:
    # The dominant false positive: a decision legitimately names another axis to say it is
    # DISTINCT FROM it. That axis routes to itself; naming it is correct, not drift.
    settled = [
        {"key": "governance_axis", "source_keys": ["governance_axis"],
         "decision": "Kept as a distinct axis from coop_motivation. A plausible applicant could differ."},
        {"key": "coop_motivation", "source_keys": ["coop_motivation"],
         "decision": "Intrinsic cooperative values."},
    ]
    assert find_drift(settled) == []


def test_split_routing_covered_by_is_not_flagged() -> None:
    # The real-data false positive: an input axis is split, and the decision documents that
    # a component 'is covered by <other axis>'. Naming that axis is correct routing, not
    # drift, even though it sits near absorb/merge language.
    settled = [
        {"key": "mediation_axis", "source_keys": ["mediation_axis", "bundled_pro_skills"],
         "decision": "bundled_pro_skills is absorbed here; its nursing component is covered by health_axis."},
        {"key": "health_axis", "source_keys": ["health_axis"],
         "decision": "Professional health/nursing capacity."},
    ]
    # health_axis is named in mediation_axis's decision under 'covered by' → suppressed.
    assert find_drift(settled) == []


def test_no_drift_when_folded_key_actually_routed_here() -> None:
    # A clean fold: the decision claims keys folded in, and they DID route into this axis.
    settled = [
        {"key": "trade_axis", "source_keys": ["trade_axis", "hands_on_trades", "licensed_trades"],
         "decision": "hands_on_trades and licensed_trades both measure building-trade skill; merged in here."},
    ]
    assert find_drift(settled) == []


def test_ignores_prose_words_that_are_not_input_keys() -> None:
    # snake_case-looking tokens that aren't real input keys are not flagged.
    settled = [
        {"key": "a", "source_keys": ["a"],
         "decision": "This is a self_evident concept, folded from day_to_day contribution."},
    ]
    assert find_drift(settled) == []
