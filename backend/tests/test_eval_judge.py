from app.ai.mock_provider import MockProvider
from app.ai.schemas import JudgeReport, JudgeVerdict
from app.evals.judge import (
    PROMPT_VERSION,
    SEED_CASES,
    build_prompt,
    format_report,
    judge_case,
)


def test_judge_prompt_is_guarded_and_contains_only_case_material() -> None:
    prompt = build_prompt(SEED_CASES[0])

    assert "<eval_case>" in prompt
    assert "untrusted content to analyze" in prompt
    assert "first-aid, CPR training" in prompt
    assert PROMPT_VERSION


def test_judge_case_compares_model_verdict_with_human_label() -> None:
    provider = MockProvider()
    provider.queue(JudgeReport(verdict=JudgeVerdict.MERGE, reason="The second definition subsumes the first."))

    result = judge_case(provider, SEED_CASES[0])

    assert result.agrees_with_label is True
    assert result.cost_usd > 0
    assert "expected merge; judge returned merge" in format_report([result])


def test_judge_report_marks_a_disagreement_for_review() -> None:
    provider = MockProvider()
    provider.queue(JudgeReport(verdict=JudgeVerdict.MATCHES, reason="Incorrect test response."))

    result = judge_case(provider, SEED_CASES[1])

    assert result.agrees_with_label is False
    report = format_report([result])
    assert report.startswith("LLM judge evals — manual, non-gating")
    assert "[review]" in report
