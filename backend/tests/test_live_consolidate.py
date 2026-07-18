"""Structural guard + plumbing test for the live consolidation eval (M13).

The live eval makes real model calls (opt-in, not CI). These are the cheap CI half: the
golden fixture loads and is well-formed; run_case grades a produced verdict against the label
by exact match; and — when a case carries a judge question — the independent judge also runs
as a label audit (informational, never gating). A MockProvider stands in for Bedrock.
"""

from dataclasses import replace

from app.ai.mock_provider import MockProvider
from app.ai.schemas import (
    ConsolidationReport,
    ConsolidationVerdict,
    JudgeReport,
    JudgeVerdict,
)
from app.evals.live_consolidate import load_cases, run_case, stability_run

_VERDICTS = {"merge", "keep"}


def test_golden_cases_load_well_formed() -> None:
    cases = load_cases()
    assert cases, "consolidation golden fixture has no cases"
    assert len({c.key for c in cases}) == len(cases), "duplicate case keys"
    for c in cases:
        assert c.expected in _VERDICTS, f"{c.key}: expected must be merge|keep"
        assert len(c.pair) == 2, f"{c.key}: needs exactly two descriptors"
        for d in c.pair:
            assert d.get("key"), f"{c.key}: descriptor needs a key"
            assert d.get("definition"), f"{c.key}: descriptor needs a definition"


def _mock_confirm(case, *, same_concept: bool, judge: str | None = None) -> MockProvider:
    """A provider that returns one confirm verdict for the case's pair, and (if ``judge`` is
    given) a judge report routed by the judge prompt's MERGE/KEEP task text."""
    a, b = case.pair
    provider = MockProvider()
    provider.route(
        "candidate_pairs",  # the confirm prompt wraps the pair in this tag
        ConsolidationReport(verdicts=[
            ConsolidationVerdict(key_a=str(a["key"]), key_b=str(b["key"]),
                                 same_concept=same_concept, reason="test"),
        ]),
    )
    if judge is not None:
        provider.route("MERGE or KEEP",  # the judge case's task text
                       JudgeReport(verdict=JudgeVerdict(judge), reason="judge test"))
    return provider


def test_run_case_passes_when_verdict_matches_label() -> None:
    case = next(c for c in load_cases() if c.expected == "keep" and not c.contested)
    provider = _mock_confirm(case, same_concept=False)  # keep

    chunks: list[str] = []
    result = run_case(provider, case, consolidate_model="m", on_delta=chunks.append)

    assert result.verdict == "keep"
    assert result.passed is True
    assert not result.failures
    narration = "".join(chunks)
    assert "Verdict: keep" in narration
    assert "matches the label" in narration


def test_run_case_fails_when_verdict_disagrees() -> None:
    case = next(c for c in load_cases() if c.expected == "keep" and not c.contested)
    provider = _mock_confirm(case, same_concept=True)  # merge, disagreeing with keep

    result = run_case(provider, case, consolidate_model="m")

    assert result.verdict == "merge"
    assert result.passed is False
    assert result.failures


def test_contested_case_never_fails_on_direction() -> None:
    """A contested case has no honest verdict pass/fail — whichever way it lands, no failure
    is recorded (its signal is stability, not direction)."""
    base = next((c for c in load_cases() if c.contested), None) or replace(
        load_cases()[0], contested=True
    )
    for same in (True, False):
        result = run_case(_mock_confirm(base, same_concept=same), base, consolidate_model="m")
        assert not result.failures, "contested case must not record a verdict failure"


def test_judge_does_not_run_without_a_question() -> None:
    """The judge block is the switch: a case with no judge question never runs the judge,
    even when a judge_model is available."""
    case = next(c for c in load_cases() if not c.judge and not c.contested)
    result = run_case(_mock_confirm(case, same_concept=(case.expected == "merge")),
                      case, consolidate_model="m", judge_model="j")
    assert result.judge_verdict is None


def test_judge_runs_as_label_audit_when_question_present() -> None:
    """A case carrying a judge question runs the independent judge; its verdict is surfaced
    but never changes the exact-match pass/fail. Here the confirm matches the label (pass)
    while the judge DISAGREES — passed stays True, judge_verdict records the dissent."""
    base = next(c for c in load_cases() if c.expected == "keep" and not c.contested)
    case = replace(base, judge="Decide MERGE or KEEP for these two definitions.")
    provider = _mock_confirm(case, same_concept=False, judge="merge")  # confirm=keep, judge=merge

    chunks: list[str] = []
    result = run_case(provider, case, consolidate_model="m", judge_model="j", on_delta=chunks.append)

    assert result.verdict == "keep"
    assert result.passed is True  # exact-match still passes; judge never gates
    assert result.judge_verdict == "merge"  # the audit dissent is surfaced
    assert "DISAGREES with the label" in "".join(chunks)


def test_stability_stable_when_verdict_never_flips() -> None:
    """K identical verdicts ⇒ [stable], full agreement, not flipped."""
    case = next(c for c in load_cases() if not c.contested)
    provider = _mock_confirm(case, same_concept=(case.expected == "merge"))
    rep = stability_run(provider, case, consolidate_model="m", k=4)
    assert not rep.flipped
    assert rep.agreement == 1.0
    assert rep.marker == "[stable]"


def test_stability_contested_flip_reads_as_contested_split() -> None:
    """A contested case that flips is expected — marker is [contested-split], never [UNSTABLE]."""
    base = next((c for c in load_cases() if c.contested), None) or replace(
        load_cases()[0], contested=True
    )
    # A provider that alternates merge/keep across the K calls to force a flip.
    a, b = base.pair
    provider = MockProvider()
    for same in (True, False):  # queue enough alternating verdicts for K=4
        for _ in range(2):
            provider.queue(ConsolidationReport(verdicts=[
                ConsolidationVerdict(key_a=str(a["key"]), key_b=str(b["key"]),
                                     same_concept=same, reason="t"),
            ]))
    rep = stability_run(provider, base, consolidate_model="m", k=4)
    assert rep.flipped
    assert rep.marker == "[contested-split]"
