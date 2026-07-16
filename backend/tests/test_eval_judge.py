from app.ai.mock_provider import MockProvider
from app.ai.schemas import JudgeReport, JudgeVerdict
from app.evals.judge import (
    PROMPT_VERSION,
    build_prompt,
    format_report,
    judge_case,
    load_cases,
)


def test_cases_load_with_label_rationale() -> None:
    cases = load_cases()

    assert cases, "expected at least one committed judge case"
    for case in cases:
        # Every committed case is exact and human-labelled: it must carry the WHY, not a
        # bare verdict, so a disagreement can be weighed against the recorded reasoning.
        assert case.label_rationale, f"{case.key} has no label_rationale"
        assert case.source, f"{case.key} has no source"


def test_judge_prompt_is_guarded_and_contains_only_case_material() -> None:
    case = load_cases()[0]
    prompt = build_prompt(case)

    assert "<eval_case>" in prompt
    assert "untrusted content to analyze" in prompt
    # The case's own evidence rides in the prompt; the label rationale must NOT (it would
    # reveal the expected verdict to the judge — see the eval design rules).
    assert next(iter(case.evidence.values()))[:40] in prompt
    assert case.label_rationale not in prompt
    assert PROMPT_VERSION


def test_judge_case_agrees_when_verdict_matches_label() -> None:
    case = load_cases()[0]
    provider = MockProvider()
    provider.queue(JudgeReport(verdict=case.expected, reason="Matches the recorded label."))

    result = judge_case(provider, case)

    assert result.agrees_with_label is True
    assert result.cost_usd > 0
    assert f"expected {case.expected.value}; judge returned {case.expected.value}" in format_report([result])


def test_judge_report_marks_a_disagreement_for_review() -> None:
    case = load_cases()[0]
    disagreeing = JudgeVerdict.MERGE if case.expected != JudgeVerdict.MERGE else JudgeVerdict.KEEP
    provider = MockProvider()
    provider.queue(JudgeReport(verdict=disagreeing, reason="Deliberately opposite verdict."))

    result = judge_case(provider, case)

    assert result.agrees_with_label is False
    report = format_report([result])
    assert report.startswith("LLM judge evals — manual, non-gating")
    assert "[review]" in report
