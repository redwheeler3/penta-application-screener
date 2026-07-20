"""Structural guard for the live scoring eval's golden fixture (M13).

The live eval itself (``app/evals/scoring.py``) makes real model calls, so it is an
opt-in run, NOT part of CI. These tests are the cheap CI half: they confirm the golden
fixture loads and is well-formed — every case has both poles, a checkable expected band, and
any bound sits in the signed [-1, 1] range — so a malformed fixture fails at commit time
rather than at spend time. No model is invoked here. Scoring is graded DETERMINISTICALLY (the
produced score must land in the expected band); there is no inline judge (see the Judge tab).
"""

from app.ai.mock_provider import MockProvider
from app.ai.schemas import (
    DimensionScore,
    DimensionScoringReport,
    ScoreConfidence,
)
from app.evals.scoring import load_golden, run_case, stability_run

_EXPECT_KEYS = {"score_min", "score_max", "confidence"}


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
        assert _EXPECT_KEYS & set(c.expected), f"{c.key}: expected has no checkable property"
        for k in ("score_min", "score_max"):
            if k in c.expected:
                assert -1.0 <= float(c.expected[k]) <= 1.0, f"{c.key}: {k} out of [-1, 1]"
        if "confidence" in c.expected:
            # May be a single value ("low") or an any-of set ("medium | high"); every token
            # must be a real confidence level.
            allowed = {t.strip() for t in str(c.expected["confidence"]).split("|")}
            assert allowed <= {"low", "medium", "high"}, f"{c.key}: bad confidence expectation"


def _score(value: float, confidence: ScoreConfidence) -> DimensionScore:
    return DimensionScore(
        dimension_key="d", score=value, confidence=confidence, rationale="r", evidence="e",
    )


def test_confidence_any_of_accepts_either_and_rejects_others() -> None:
    """A `"medium | high"` expectation accepts EITHER produced level (any-of, like screening's
    fire groups) but still rejects a value outside the set — the fix for a `|` band that used to
    be compared as one literal string (so it could never match)."""
    from app.evals.scoring import _check_expectations

    expected = {"score_min": 0.2, "score_max": 0.7, "confidence": "medium | high"}
    assert _check_expectations(_score(0.5, ScoreConfidence.MEDIUM), expected) == []
    assert _check_expectations(_score(0.5, ScoreConfidence.HIGH), expected) == []
    fails = _check_expectations(_score(0.5, ScoreConfidence.LOW), expected)
    assert any("confidence" in f for f in fails)


def test_confidence_single_value_still_exact() -> None:
    from app.evals.scoring import _check_expectations

    expected = {"confidence": "low"}
    assert _check_expectations(_score(0.0, ScoreConfidence.LOW), expected) == []
    assert _check_expectations(_score(0.0, ScoreConfidence.MEDIUM), expected)


def test_run_case_narrates_score_to_the_sink() -> None:
    """The Evals tab shows a live "thinking" box; scoring one item is a tight structured_output
    call that emits no free-form reasoning, so run_case EMULATES the narration from the real
    output. This pins that the score's grounding and the band-check outcome reach the sink (the
    regression: an empty thinking box)."""
    case = load_golden()[0]
    provider = MockProvider()
    provider.route(
        case.dimension.key,
        DimensionScoringReport(scores=[DimensionScore(
            dimension_key=case.dimension.key, score=0.0,
            confidence=ScoreConfidence.LOW, rationale="Nothing stated on this dimension.",
            evidence="No mention in the application.",
        )]),
    )

    chunks: list[str] = []
    result = run_case(provider, case, scoring_model="score-model", on_delta=chunks.append)
    narration = "".join(chunks)

    assert "Score +0.00" in narration
    assert "Nothing stated on this dimension." in narration
    assert "No mention in the application." in narration
    assert result.passed  # a neutral score on a silent applicant lands in the expected band


def test_run_case_works_without_a_sink() -> None:
    """on_delta is optional — omitting it must not change the graded result (other callers
    pass none)."""
    case = load_golden()[0]
    provider = MockProvider()
    provider.route(
        case.dimension.key,
        DimensionScoringReport(scores=[DimensionScore(
            dimension_key=case.dimension.key, score=0.0,
            confidence=ScoreConfidence.LOW, rationale="r", evidence="e",
        )]),
    )

    result = run_case(provider, case, scoring_model="m")
    assert result.score == 0.0


def _score_provider(case, scores: list[float]) -> MockProvider:
    """A provider that returns the given scores in order across successive scoring calls. Uses
    the FIFO queue so each call pops the next score."""
    provider = MockProvider()
    for s in scores:
        provider.queue(DimensionScoringReport(scores=[DimensionScore(
            dimension_key=case.dimension.key, score=s,
            confidence=ScoreConfidence.LOW, rationale="r", evidence="e",
        )]))
    return provider


def _neutral_case():
    """A case whose expected band straddles 0 (a symmetric min/max around neutral)."""
    return next(
        c for c in load_golden()
        if c.expected.get("score_min", -1) <= 0 <= c.expected.get("score_max", 1)
        and "score_min" in c.expected and "score_max" in c.expected
    )


def test_stability_stable_when_band_holds_every_run() -> None:
    """A neutral case (expects a band around 0) that scores ~0 every run is [stable] — the band
    check passes on all K, no flip."""
    case = _neutral_case()
    res = stability_run(_score_provider(case, [0.0, 0.02, -0.01, 0.0]), case, scoring_model="m", k=4)
    assert not res.stability.flipped
    assert res.stability.marker == "[stable]"
    assert res.stability.agreement == 1.0


def test_stability_unstable_when_score_crosses_the_band_boundary() -> None:
    """The real signal: the score wanders ACROSS the pass/fail line — some runs land in the
    band, some don't — so the pass/fail flips even though no single number repeats."""
    case = _neutral_case()
    # 0.0 passes (in band), 0.8 fails (outside the neutral band): the outcome flips.
    res = stability_run(_score_provider(case, [0.0, 0.8, 0.0, 0.9]), case, scoring_model="m", k=4)
    assert res.stability.flipped
    assert res.stability.marker == "[UNSTABLE]"
    assert set(res.stability.tally) == {"pass", "fail"}
    assert res.score_spread == (0.0, 0.9)
