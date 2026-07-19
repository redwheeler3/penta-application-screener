"""Structural guard + plumbing test for the live decomposition eval (M13).

The live eval makes real model calls (opt-in, not CI). These are the cheap CI half: the
golden fixture loads and is well-formed, and run_case derives merge/keep from the settled set
(all carvings in one axis = merge; spread across ≥2 = keep) and grades it against the label.
A MockProvider stands in for Bedrock.
"""

from dataclasses import replace

from app.ai.mock_provider import MockProvider
from app.ai.schemas import DecomposedDimension, DecompositionReport
from app.evals.live_decompose import load_cases, run_case, stability_run

_VERDICTS = {"merge", "keep"}


def test_golden_cases_load_well_formed() -> None:
    cases = load_cases()
    assert cases, "decomposition golden fixture has no cases"
    assert len({c.key for c in cases}) == len(cases), "duplicate case keys"
    for c in cases:
        assert c.expected in _VERDICTS, f"{c.key}: expected must be merge|keep"
        assert len(c._source_keys) >= 2, f"{c.key}: needs ≥2 carvings to fold/keep"


def _axis(key: str, source_keys: list[str]) -> DecomposedDimension:
    return DecomposedDimension(
        key=key, name=key, definition="d", high_end="h", low_end="l",
        source_keys=source_keys, decision="test",
    )


def _mock_merge(case) -> MockProvider:
    """A provider whose settled set folds ALL the case's source keys into ONE axis."""
    provider = MockProvider()
    provider.route("discovery_reports", DecompositionReport(
        dimensions=[_axis("folded", sorted(case._source_keys))],
    ))
    return provider


def _mock_keep(case) -> MockProvider:
    """A provider whose settled set keeps each source key in its OWN axis (≥2 axes)."""
    provider = MockProvider()
    provider.route("discovery_reports", DecompositionReport(
        dimensions=[_axis(k, [k]) for k in sorted(case._source_keys)],
    ))
    return provider


def test_run_case_merge_passes_when_all_folded() -> None:
    case = next(c for c in load_cases() if c.expected == "merge")
    result = run_case(_mock_merge(case), case, decompose_model="m")
    assert result.verdict == "merge"
    assert result.passed is True


def test_run_case_merge_fails_when_kept_apart() -> None:
    case = next(c for c in load_cases() if c.expected == "merge")
    result = run_case(_mock_keep(case), case, decompose_model="m")  # produced keep
    assert result.verdict == "keep"
    assert result.passed is False
    assert result.failures


def test_run_case_keep_passes_when_kept_apart() -> None:
    case = next(c for c in load_cases() if c.expected == "keep")
    result = run_case(_mock_keep(case), case, decompose_model="m")
    assert result.verdict == "keep"
    assert result.passed is True


def test_stability_stable_when_verdict_never_flips() -> None:
    case = next(c for c in load_cases() if c.expected == "merge")
    rep = stability_run(_mock_merge(case), case, decompose_model="m", k=4)
    assert not rep.flipped
    assert rep.marker == "[stable]"


def test_contested_flip_reads_as_contested_split() -> None:
    base = replace(load_cases()[0], contested=True)
    keys = sorted(base._source_keys)
    provider = MockProvider()
    # Alternate folded/kept across K to force a flip.
    for merged in (True, False, True, False):
        provider.queue(DecompositionReport(
            dimensions=[_axis("folded", keys)] if merged else [_axis(k, [k]) for k in keys],
        ))
    rep = stability_run(provider, base, decompose_model="m", k=4)
    assert rep.flipped
    assert rep.marker == "[contested-split]"
