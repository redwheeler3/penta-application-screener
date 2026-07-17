"""Structural guard for the live scoring eval's golden fixture (M13).

The live eval itself (``app/evals/live_scoring.py``) makes real model calls, so it is an
opt-in run, NOT part of CI. These tests are the cheap CI half: they confirm the golden
fixture loads and is well-formed — every case has both poles, a checkable expectation, and
any bound sits in the signed [-1, 1] range — so a malformed fixture fails at commit time
rather than at spend time. No model is invoked here.
"""

from app.evals.live_scoring import load_golden

_EXPECT_KEYS = {"score_equals", "score_min", "score_max", "confidence"}


def test_golden_cases_load() -> None:
    cases = load_golden()
    assert cases, "golden fixture has no cases"
    assert len({c.key for c in cases}) == len(cases), "duplicate case keys"


def test_each_case_is_well_formed() -> None:
    for c in load_golden():
        assert c.dimension.high_end.strip(), f"{c.key}: high_end pole must be stated"
        assert c.dimension.low_end.strip(), f"{c.key}: low_end pole must be stated"
        assert c.applicant.get("essays") or c.applicant.get("facts"), (
            f"{c.key}: applicant needs facts or essays to score on"
        )
        # At least one checkable expectation, and every numeric bound in [-1, 1].
        assert _EXPECT_KEYS & set(c.expect), f"{c.key}: expect has no checkable property"
        for k in ("score_equals", "score_min", "score_max"):
            if k in c.expect:
                assert -1.0 <= float(c.expect[k]) <= 1.0, f"{c.key}: {k} out of [-1, 1]"
        if "confidence" in c.expect:
            assert c.expect["confidence"] in {"low", "medium", "high"}, (
                f"{c.key}: bad confidence expectation"
            )
