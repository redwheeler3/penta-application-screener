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
    format_report,
    format_stability,
    judge_case,
    load_cases,
    prompt_version,
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

    narration: list[str] = []
    report = stability_run(provider, case, k=5, on_delta=narration.append)

    assert len(report.labels) == 5
    assert report.agreement == 1.0
    assert report.flipped is False
    assert report.majority == case.expected
    assert report.total_cost_usd > 0
    assert "[stable]" in format_stability([report])
    # Every run keeps its reasoning (parallel to labels), so a stable run shows its K reasonings
    # too — the judge stability was dropping this while the other passes retained it.
    assert len(report.runs) == 5
    assert all(r.outcome == case.expected for r in report.runs)
    assert all(isinstance(r.detail, str) for r in report.runs)
    # …and those K reasonings are narrated to the thinking box (one numbered line per run),
    # like the other passes' stability — not just the detail pane.
    assert sum(line.startswith("- run ") for line in narration) == 5


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


def test_scoring_stability_tokens_by_in_band_not_raw_score() -> None:
    """A CONTINUOUS pass: different in-band scores are the SAME stability outcome. Three distinct
    scores that all land in the band must read [stable] (100% agree), not [UNSTABLE] from tallying
    the raw score strings — the bug that showed 60% on modest_evidence_scores_mid even though every
    run agreed. A score that leaves the band is a real flip."""
    from app.ai.schemas import DimensionScore, DimensionScoringReport, ScoreConfidence

    case = next(c for c in load_cases() if c.pass_name == "scoring")
    band = case.expected  # e.g. {"score_min": ..., "score_max": ..., ...}
    lo, hi = float(band["score_min"]), float(band["score_max"])
    mid = (lo + hi) / 2
    in_band = [lo + (hi - lo) * f for f in (0.2, 0.5, 0.8)]  # three DIFFERENT in-band scores
    # Use a confidence the case accepts (it may pin one), so only the SCORE decides agreement.
    conf = ScoreConfidence(str(band.get("confidence", "medium")).split("|")[0].strip())

    def _report(score_val: float) -> DimensionScoringReport:
        dim_key = case.given["dimension"]["key"]
        return DimensionScoringReport(scores=[DimensionScore(
            dimension_key=dim_key, score=score_val, confidence=conf,
            rationale="r", evidence="e",
        )])

    provider = MockProvider()
    for s in in_band:
        provider.queue(_report(s))
    steady = stability_run(provider, case, k=3)
    assert steady.agreement == 1.0
    assert steady.flipped is False
    assert "[stable]" in format_stability([steady])

    # A score that leaves the band IS a real flip (agrees -> disagrees). Pick a valid (-1..1)
    # out-of-band value: just below lo, or just above hi if lo is at the floor.
    out_of_band = round(lo - 0.1, 2) if lo - 0.1 >= -1.0 else round(hi + 0.1, 2)
    provider = MockProvider()
    provider.queue(_report(mid))          # in band  -> agrees
    provider.queue(_report(out_of_band))  # out band -> disagrees
    provider.queue(_report(mid))          # in band  -> agrees
    flipped = stability_run(provider, case, k=3)
    assert flipped.flipped is True
    assert "[UNSTABLE]" in format_stability([flipped])


def test_prompt_version_tracks_the_briefs() -> None:
    """The judge version is a hash of the five editable briefs, so editing any brief changes it
    (that is what marks a prior judge run stale). Same briefs -> same version; a changed brief ->
    a different version."""
    import json

    from app.evals import judge

    v1 = prompt_version()
    assert isinstance(v1, str)
    assert v1
    assert prompt_version() == v1  # deterministic for unchanged briefs

    # Point one pass at a golden file whose brief differs; the hash must move.
    path = judge._PASS_FILES["scoring"]
    original = path.read_text()
    try:
        data = json.loads(original)
        data["judge_background"] = (data.get("judge_background", "") + " EDITED FOR TEST")
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        assert prompt_version() != v1
    finally:
        path.write_text(original)
    assert prompt_version() == v1  # restored
