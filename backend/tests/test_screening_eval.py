"""Structural guard + plumbing test for the live screening eval (M13).

The live eval makes real model calls (opt-in, not CI). These are the cheap CI half: the
golden fixture loads and is well-formed, and run_case grades the produced flag categories
per-case (expected fires present, guarded categories absent, clean applicants flag-free). A
MockProvider stands in for Bedrock; settings come from a minimal AppSettings.
"""

from app.ai.mock_provider import MockProvider
from app.ai.schemas import FlagCategory, FlagSeverity, ScreeningFlag, ScreeningReport
from app.evals.screening import load_cases, run_case, stability_run
from app.schemas.settings import AppSettings


def _settings() -> AppSettings:
    return AppSettings()


def test_golden_cases_load_well_formed() -> None:
    cases = load_cases()
    assert cases, "screening golden fixture has no cases"
    assert len({c.key for c in cases}) == len(cases), "duplicate case keys"
    for c in cases:
        assert c.fields.get("applicant_name"), f"{c.key}: needs an applicant_name"


def _mock_flags(*categories: FlagCategory) -> MockProvider:
    """A provider returning a ScreeningReport with the given flag categories."""
    provider = MockProvider()
    provider.route("<fields>", ScreeningReport(flags=[
        ScreeningFlag(category=c, severity=FlagSeverity.NOTABLE, summary="s", evidence="e")
        for c in categories
    ]))
    return provider


def test_fires_case_passes_when_expected_flag_present() -> None:
    case = next(c for c in load_cases() if c.fires)
    cat = FlagCategory(case.fires[0])
    result = run_case(_mock_flags(cat), case, screening_model="m", settings=_settings())
    assert result.passed is True
    assert case.fires[0] in result.categories


def test_fires_case_fails_when_expected_flag_missing() -> None:
    case = next(c for c in load_cases() if c.fires)
    result = run_case(_mock_flags(), case, screening_model="m", settings=_settings())  # no flags
    assert result.passed is False
    assert any("did not fire" in f for f in result.failures)


def test_over_reach_guard_fails_when_guarded_flag_fires() -> None:
    case = next(c for c in load_cases() if c.absent)
    bad = FlagCategory(case.absent[0])
    result = run_case(_mock_flags(bad), case, screening_model="m", settings=_settings())
    assert result.passed is False
    assert any("over-reach" in f for f in result.failures)


def test_clean_case_fails_on_any_flag() -> None:
    case = next(c for c in load_cases() if not c.fires and not c.absent)
    clean = run_case(_mock_flags(), case, screening_model="m", settings=_settings())
    assert clean.passed is True
    noisy = run_case(_mock_flags(FlagCategory.PET_POLICY), case, screening_model="m", settings=_settings())
    assert noisy.passed is False


def test_stability_flags_a_changing_flag_set() -> None:
    """The flag SET changing run-to-run is the instability signal: no flags one run,
    pet_policy the next → flipped, [UNSTABLE]."""
    case = load_cases()[0]
    provider = MockProvider()
    for cats in ([], [FlagCategory.PET_POLICY], [], [FlagCategory.PET_POLICY]):
        provider.queue(ScreeningReport(flags=[
            ScreeningFlag(category=c, severity=FlagSeverity.NOTABLE, summary="s", evidence="e")
            for c in cats
        ]))
    rep = stability_run(provider, case, screening_model="m", settings=_settings(), k=4)
    assert rep.flipped
    assert rep.marker == "[UNSTABLE]"
