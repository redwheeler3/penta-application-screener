"""Structural guard + plumbing test for the live matching eval (M13).

The live eval makes real model calls (opt-in, not CI). These are the cheap CI half: the
golden fixture loads and is well-formed, and run_case grades a produced matches/mismatches
verdict against the label by exact match. A MockProvider stands in for Bedrock.
"""

from dataclasses import replace

from app.ai.mock_provider import MockProvider
from app.ai.schemas import DimensionMatch, DimensionMatchReport
from app.evals.matching import load_cases, run_case, stability_run

_VERDICTS = {"matches", "mismatches"}


def test_golden_cases_load_well_formed() -> None:
    cases = load_cases()
    assert cases, "matching golden fixture has no cases"
    assert len({c.key for c in cases}) == len(cases), "duplicate case keys"
    for c in cases:
        assert c.expected in _VERDICTS, f"{c.key}: expected must be matches|mismatches"
        assert c.prior, f"{c.key}: needs a prior descriptor"
        assert c.new, f"{c.key}: needs a new descriptor"
        for d in (*c.prior, *c.new):
            assert d.get("key"), f"{c.key}: descriptor needs a key"
            assert d.get("definition"), f"{c.key}: descriptor needs a definition"


def _mock_match(case, *, matched: bool) -> MockProvider:
    """A provider that returns a match report — mapping new→prior when ``matched``, else empty
    (no mapping = mismatches for this pair)."""
    provider = MockProvider()
    matches = []
    if matched:
        matches.append(DimensionMatch(new_key=str(case.new[0]["key"]), old_key=str(case.prior[0]["key"])))
    provider.route("prior_dimensions", DimensionMatchReport(matches=matches))
    return provider


def test_run_case_passes_when_verdict_matches_label() -> None:
    case = next(c for c in load_cases() if c.expected == "matches")
    result = run_case(_mock_match(case, matched=True), case, match_model="m")
    assert result.verdict == "matches"
    assert result.passed is True
    assert not result.failures


def test_run_case_fails_when_verdict_disagrees() -> None:
    case = next(c for c in load_cases() if c.expected == "matches")
    result = run_case(_mock_match(case, matched=False), case, match_model="m")  # produced mismatches
    assert result.verdict == "mismatches"
    assert result.passed is False
    assert result.failures


def test_mismatch_case_passes_when_model_declines_to_map() -> None:
    case = next(c for c in load_cases() if c.expected == "mismatches")
    result = run_case(_mock_match(case, matched=False), case, match_model="m")
    assert result.verdict == "mismatches"
    assert result.passed is True


def test_stability_stable_when_verdict_never_flips() -> None:
    case = next(c for c in load_cases() if c.expected == "matches")
    rep = stability_run(_mock_match(case, matched=True), case, match_model="m", k=4)
    assert not rep.flipped
    assert rep.marker == "[stable]"
    assert rep.agreement == 1.0


def test_contested_flip_reads_as_contested_split() -> None:
    base = replace(load_cases()[0], contested=True)
    # Alternate matched/not across K to force a flip.
    a_prior, a_new = str(base.prior[0]["key"]), str(base.new[0]["key"])
    provider = MockProvider()
    for matched in (True, False, True, False):
        provider.queue(DimensionMatchReport(
            matches=[DimensionMatch(new_key=a_new, old_key=a_prior)] if matched else [],
        ))
    rep = stability_run(provider, base, match_model="m", k=4)
    assert rep.flipped
    assert rep.marker == "[contested-split]"
