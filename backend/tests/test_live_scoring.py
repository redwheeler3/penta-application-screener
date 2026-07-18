"""Structural guard for the live scoring eval's golden fixture (M13).

The live eval itself (``app/evals/live_scoring.py``) makes real model calls, so it is an
opt-in run, NOT part of CI. These tests are the cheap CI half: they confirm the golden
fixture loads and is well-formed — every case has both poles, a checkable expectation, and
any bound sits in the signed [-1, 1] range — so a malformed fixture fails at commit time
rather than at spend time. No model is invoked here.
"""

from app.ai.mock_provider import MockProvider
from app.ai.schemas import (
    DimensionScore,
    DimensionScoringReport,
    JudgeReport,
    JudgeVerdict,
    ScoreConfidence,
)
from app.evals.live_scoring import load_golden, run_case

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
        # Every case carries the required judge question (the single source for the rubric
        # judge's task AND the UI title) — grading is assertions AND judge on every case.
        assert c.judge, f"{c.key}: judge question is required"
        assert c.judge.strip(), f"{c.key}: judge question must not be blank"
        # At least one checkable expectation, and every numeric bound in [-1, 1].
        assert _EXPECT_KEYS & set(c.expect), f"{c.key}: expect has no checkable property"
        for k in ("score_equals", "score_min", "score_max"):
            if k in c.expect:
                assert -1.0 <= float(c.expect[k]) <= 1.0, f"{c.key}: {k} out of [-1, 1]"
        if "confidence" in c.expect:
            assert c.expect["confidence"] in {"low", "medium", "high"}, (
                f"{c.key}: bad confidence expectation"
            )


def test_run_case_narrates_score_and_judge_to_the_sink() -> None:
    """The Evals tab shows a live "thinking" box; scoring/judging one item are tight
    structured_output calls that emit no free-form reasoning, so run_case EMULATES the
    narration from the real output. This pins that the score's grounding AND the judge's
    verdict+reason reach the sink (the regression: an empty thinking box)."""
    case = load_golden()[0]  # every case is judged, so any exercises both phases
    provider = MockProvider()
    provider.route(
        case.dimension.key,
        DimensionScoringReport(scores=[DimensionScore(
            dimension_key=case.dimension.key, score=0.0,
            confidence=ScoreConfidence.LOW, rationale="Nothing stated on this dimension.",
            evidence="No mention in the application.",
        )]),
    )
    provider.route(
        "SUPPORTED or UNSUPPORTED",  # the judge task text routes the judge call
        JudgeReport(verdict=JudgeVerdict.SUPPORTED, reason="Neutral is defensible on silence."),
    )

    chunks: list[str] = []
    result = run_case(
        provider, case, scoring_model="score-model", judge_model="judge-model",
        on_delta=chunks.append,
    )
    narration = "".join(chunks)

    # The score, its rationale/evidence, and the judge's verdict+reason all narrated.
    assert "Score +0.00" in narration
    assert "Nothing stated on this dimension." in narration
    assert "No mention in the application." in narration
    assert "Judge: supported" in narration
    assert "Neutral is defensible on silence." in narration
    assert result.judge_verdict is JudgeVerdict.SUPPORTED


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
    provider.route(
        "SUPPORTED or UNSUPPORTED",  # every case is judged; route the judge call too
        JudgeReport(verdict=JudgeVerdict.SUPPORTED, reason="ok"),
    )

    result = run_case(provider, case, scoring_model="m", judge_model="j")
    assert result.score == 0.0
