"""Plumbing tests for the blind label-audit (Judge tab).

The judge reproduces each pass's output from an editable brief + the case's given, BLIND to the
human label, then grades the blind output with that pass's grader (see app/evals/judge.py). The
live evals make real model calls; these are the cheap CI half with a MockProvider standing in
for Bedrock. They use CATEGORICAL cases (consolidation/matching/decomposition), whose adapters
reproduce a JudgeReport verdict — the simplest to drive deterministically.
"""

from app.ai.mock_provider import MockProvider
from app.ai.schemas import JudgeReport, JudgeVerdict
from app.evals.judge import (
    PROMPT_VERSION,
    format_report,
    format_stability,
    judge_case,
    load_cases,
    stability_run,
)

# The categorical passes reproduce a merge/keep (or matches/mismatches) JudgeReport verdict.
_CATEGORICAL = {"consolidation", "decomposition", "matching"}


def _a_categorical_case(*, contested: bool = False):
    return next(c for c in load_cases() if c.pass_name in _CATEGORICAL and c.contested == contested)


def test_cases_load_across_all_passes() -> None:
    cases = load_cases()
    assert cases, "expected golden cases aggregated across the passes"
    passes = {c.pass_name for c in cases}
    # The judge reads every pass's golden file, so more than one pass must show up.
    assert len(passes) >= 2, f"expected multiple passes, got {passes}"
    for case in cases:
        assert case.background, f"{case.key}: pass has no judge_background"
        assert case.given, f"{case.key}: no given payload for the judge to reproduce from"


def test_judge_agrees_when_reproduced_verdict_matches_label() -> None:
    case = _a_categorical_case()
    provider = MockProvider()
    provider.queue(JudgeReport(verdict=JudgeVerdict(case.expected), reason="Matches the label."))

    result = judge_case(provider, case)

    assert result.agrees_with_label is True
    assert result.cost_usd > 0
    assert result.marker == "[ok]"
    assert "[ok]" in format_report([result])


def test_judge_marks_a_disagreement_for_review() -> None:
    case = _a_categorical_case()
    other = JudgeVerdict.MERGE if case.expected != "merge" else JudgeVerdict.KEEP
    # matching cases use matches/mismatches, not merge/keep — pick a valid opposite.
    if case.pass_name == "matching":
        other = JudgeVerdict.MATCHES if case.expected != "matches" else JudgeVerdict.MISMATCHES
    provider = MockProvider()
    provider.queue(JudgeReport(verdict=other, reason="Deliberately opposite verdict."))

    result = judge_case(provider, case)

    assert result.agrees_with_label is False
    assert result.marker == "[review]"
    assert "[review]" in format_report([result])


def test_contested_case_never_marks_ok_regardless_of_verdict() -> None:
    contested = _a_categorical_case(contested=True)
    for verdict in (JudgeVerdict.MERGE, JudgeVerdict.KEEP):
        provider = MockProvider()
        provider.queue(JudgeReport(verdict=verdict, reason="Either way is defensible."))
        result = judge_case(provider, contested)
        assert result.marker == "[contested]"
        report = format_report([result])
        assert "[contested]" in report
        assert "[ok]" not in report


def _queue_verdicts(provider, verdicts):
    for v in verdicts:
        provider.queue(JudgeReport(verdict=v, reason="test"))


def test_stability_reports_perfect_agreement_when_verdict_is_steady() -> None:
    case = _a_categorical_case()
    provider = MockProvider()
    _queue_verdicts(provider, [JudgeVerdict(case.expected)] * 5)

    report = stability_run(provider, case, k=5)

    assert len(report.labels) == 5
    assert report.agreement == 1.0
    assert report.flipped is False
    assert report.majority == case.expected
    assert report.total_cost_usd > 0
    assert "[stable]" in format_stability([report])


def test_stability_flags_a_flip_on_a_non_contested_case() -> None:
    case = _a_categorical_case()
    a, b = (JudgeVerdict.MERGE, JudgeVerdict.KEEP)
    if case.pass_name == "matching":
        a, b = (JudgeVerdict.MATCHES, JudgeVerdict.MISMATCHES)
    provider = MockProvider()
    _queue_verdicts(provider, [a, b, a, b, a])  # 3 vs 2 → flipped, 60%

    report = stability_run(provider, case, k=5)

    assert report.flipped is True
    assert report.agreement == 0.6
    assert report.majority == a.value
    assert "[UNSTABLE]" in format_stability([report])


def test_stability_marks_a_contested_flip_as_split_not_unstable() -> None:
    contested = _a_categorical_case(contested=True)
    provider = MockProvider()
    _queue_verdicts(provider, [JudgeVerdict.MERGE, JudgeVerdict.KEEP, JudgeVerdict.MERGE])

    report = stability_run(provider, contested, k=3)

    assert report.flipped is True
    out = format_stability([report])
    assert "[contested-split]" in out
    assert "[UNSTABLE]" not in out


def test_prompt_version_is_a_stable_identifier() -> None:
    assert PROMPT_VERSION == "blind-audit"
