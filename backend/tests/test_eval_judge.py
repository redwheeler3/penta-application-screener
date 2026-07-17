from app.ai.mock_provider import MockProvider
from app.ai.schemas import JudgeReport, JudgeVerdict
from app.evals.judge import (
    PROMPT_VERSION,
    build_prompt,
    format_report,
    format_stability,
    judge_case,
    load_cases,
    stability_run,
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
    # The case's own evidence rides in the prompt — a definition, the substrate the judge
    # reasons over (matching exactly what production consolidation sees).
    assert case.evidence["definition_a"][:40] in prompt
    # The label rationale must NOT leak: it holds the human's justification, which for
    # these cases includes the r value and the diverging-applicant reasoning that
    # production does NOT see. Showing it would hand the judge the answer and break the
    # "judge sees exactly what production sees, no more" fidelity rule.
    assert case.label_rationale not in prompt
    assert "r=0.9" not in prompt  # correlation is a nomination input, never shown to the judge
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
    case = next(c for c in load_cases() if not c.contested)
    disagreeing = JudgeVerdict.MERGE if case.expected != JudgeVerdict.MERGE else JudgeVerdict.KEEP
    provider = MockProvider()
    provider.queue(JudgeReport(verdict=disagreeing, reason="Deliberately opposite verdict."))

    result = judge_case(provider, case)

    assert result.agrees_with_label is False
    report = format_report([result])
    assert report.startswith("LLM judge evals — manual, non-gating")
    assert "[review]" in report


def test_contested_case_never_marks_ok_regardless_of_verdict() -> None:
    # A contested case is review material either way — both verdicts are defensible, so
    # it must never read as a pass, and its label is a "leaning", not "expected".
    contested = next((c for c in load_cases() if c.contested), None)
    assert contested is not None, "expected at least one contested case in the committed set"

    for verdict in (JudgeVerdict.MERGE, JudgeVerdict.KEEP):
        provider = MockProvider()
        provider.queue(JudgeReport(verdict=verdict, reason="Either way is defensible."))
        result = judge_case(provider, contested)
        assert result.marker == "[contested]"
        report = format_report([result])
        assert "[contested]" in report
        assert "[ok]" not in report
        assert "leaning" in report


def _queue_verdicts(provider, verdicts):
    for v in verdicts:
        provider.queue(JudgeReport(verdict=v, reason="test"))


def test_stability_run_reports_perfect_agreement_when_verdict_is_steady() -> None:
    case = next(c for c in load_cases() if not c.contested)
    provider = MockProvider()
    _queue_verdicts(provider, [case.expected] * 5)

    report = stability_run(provider, case, k=5)

    assert len(report.verdicts) == 5
    assert report.agreement == 1.0
    assert report.flipped is False
    assert report.majority == case.expected
    assert report.total_cost_usd > 0
    assert "[stable]" in format_stability([report])


def test_stability_run_flags_a_flip_on_a_non_contested_case() -> None:
    case = next(c for c in load_cases() if not c.contested)
    provider = MockProvider()
    # 3 vs 2 split → flipped, 60% agreement, majority is the 3-side.
    _queue_verdicts(provider, [JudgeVerdict.MERGE, JudgeVerdict.KEEP,
                               JudgeVerdict.MERGE, JudgeVerdict.KEEP, JudgeVerdict.MERGE])

    report = stability_run(provider, case, k=5)

    assert report.flipped is True
    assert report.agreement == 0.6
    assert report.majority == JudgeVerdict.MERGE
    assert "[UNSTABLE]" in format_stability([report])


def test_stability_run_marks_a_contested_flip_as_split_not_unstable() -> None:
    contested = next((c for c in load_cases() if c.contested), None)
    assert contested is not None
    provider = MockProvider()
    _queue_verdicts(provider, [JudgeVerdict.MERGE, JudgeVerdict.KEEP, JudgeVerdict.MERGE])

    report = stability_run(provider, contested, k=3)

    assert report.flipped is True
    out = format_stability([report])
    # A contested case flipping is expected — informational, not an alarm.
    assert "[contested-split]" in out
    assert "[UNSTABLE]" not in out
