"""Structural guard + plumbing test for the live screening eval (M13).

The live eval makes real model calls (opt-in, not CI). These are the cheap CI half: the
golden fixture loads and is well-formed, and run_case grades the produced flag categories
per-case (expected fires present, guarded categories absent, clean applicants flag-free) plus
the extracted pet facts (M15 1e). A MockProvider stands in for Bedrock.
"""

from app.ai.mock_provider import MockProvider
from app.ai.schemas import FlagCategory, PetFacts, ScreeningFlag, ScreeningReport
from app.evals.screening import _normalize_fires, load_cases, run_case, stability_run


def test_normalize_fires_accepts_pipe_input_sugar() -> None:
    """A fires entry can be typed the way the eval DISPLAYS an any-of group ('a | b') — a
    pipe-delimited string becomes a list. Plain strings and lists pass through unchanged."""
    # Pipe string -> any-of list.
    assert _normalize_fires(["spam_essay|minimal_essay"]) == [["spam_essay", "minimal_essay"]]
    # Whitespace around pipes is trimmed (matches the 'a | b' display form).
    assert _normalize_fires(["a | b | c"]) == [["a", "b", "c"]]
    # Plain must-fire string (no pipe) is unchanged.
    assert _normalize_fires(["fake_contact"]) == ["fake_contact"]
    # An existing nested list is unchanged.
    assert _normalize_fires([["spam_essay", "minimal_essay"]]) == [["spam_essay", "minimal_essay"]]
    # The footgun: the whole value typed as a bare string is wrapped, not char-iterated.
    assert _normalize_fires("spam_essay|minimal_essay") == [["spam_essay", "minimal_essay"]]


def test_golden_cases_load_well_formed() -> None:
    cases = load_cases()
    assert cases, "screening golden fixture has no cases"
    assert len({c.key for c in cases}) == len(cases), "duplicate case keys"
    for c in cases:
        assert c.fields.get("applicant_name"), f"{c.key}: needs an applicant_name"


def _mock(*, flags: tuple[FlagCategory, ...] = (), pets: PetFacts | None = None) -> MockProvider:
    """A provider returning a ScreeningReport with the given flag categories and (optionally)
    extracted pet facts — the two halves of the report the eval grades."""
    provider = MockProvider()
    report = ScreeningReport(
        flags=[ScreeningFlag(category=c, summary="s", evidence="e") for c in flags],
        pets=pets or PetFacts(),
    )
    provider.route("<fields>", report)
    return provider


def test_fires_case_passes_when_expected_flag_present() -> None:
    case = next(c for c in load_cases() if c.fires)
    cat = FlagCategory(case.fires[0])
    result = run_case(_mock(flags=(cat,)), case, screening_model="m")
    assert result.passed is True
    assert case.fires[0] in result.categories


def test_fires_case_fails_when_expected_flag_missing() -> None:
    case = next(c for c in load_cases() if c.fires)
    result = run_case(_mock(), case, screening_model="m")  # no flags
    assert result.passed is False
    assert any("did not fire" in f for f in result.failures)


def test_over_reach_guard_fails_when_guarded_flag_fires() -> None:
    case = next(c for c in load_cases() if c.absent)
    bad = FlagCategory(case.absent[0])
    # A pet-fact case also has an `absent` guard; feed the expected pets so only the guard
    # (not a pet mismatch) drives the failure.
    pets = PetFacts(**case.expected_pets) if case.expected_pets else None
    result = run_case(_mock(flags=(bad,), pets=pets), case, screening_model="m")
    assert result.passed is False
    assert any("over-reach" in f for f in result.failures)


def test_clean_case_fails_on_any_flag() -> None:
    # A truly clean case: no fires, no absent, no pet expectation.
    case = next(
        c for c in load_cases() if not c.fires and not c.absent and c.expected_pets is None
    )
    clean = run_case(_mock(), case, screening_model="m")
    assert clean.passed is True
    noisy = run_case(_mock(flags=(FlagCategory.OTHER,)), case, screening_model="m")
    assert noisy.passed is False


def test_pet_extraction_case_grades_facts_not_flags() -> None:
    """A pet case grades the EXTRACTED inventory (M15 1e): correct counts pass even with no
    flag; wrong counts fail even with the right flags absent."""
    case = next(c for c in load_cases() if c.expected_pets is not None)
    expected = PetFacts(
        dogs=case.expected_pets.get("dogs", 0),
        cats=case.expected_pets.get("cats", 0),
        other_pets=tuple(case.expected_pets.get("other_pets", [])),
    )
    ok = run_case(_mock(pets=expected), case, screening_model="m")
    assert ok.passed is True

    wrong = run_case(
        _mock(pets=PetFacts(dogs=expected.dogs + 1, cats=expected.cats, other_pets=expected.other_pets)),
        case, screening_model="m",
    )
    assert wrong.passed is False
    assert any("dogs" in f for f in wrong.failures)


def test_contested_category_passes_whether_it_fires_or_not() -> None:
    """A contested category (named in expected.contested) is neither required nor forbidden:
    the case passes whether the model fires it or not — both are defensible."""
    from app.ai.schemas import FlagCategory

    case = next(c for c in load_cases() if c.contested)
    contested_cat = FlagCategory(case.contested[0])
    pets = PetFacts(**case.expected_pets) if case.expected_pets else None

    fired = run_case(_mock(flags=(contested_cat,), pets=pets), case, screening_model="m")
    not_fired = run_case(_mock(pets=pets), case, screening_model="m")
    assert fired.passed is True, "contested category firing must not fail the case"
    assert not_fired.passed is True, "contested category not firing must not fail the case"


def test_contested_stability_flip_reads_contested_split_not_unstable() -> None:
    """A run-to-run flip on a contested category is expected (both defensible), so it reads
    [contested-split], not [UNSTABLE] — the screening analogue of the categorical contested."""
    from app.ai.schemas import FlagCategory

    case = next(c for c in load_cases() if c.contested)
    contested_cat = FlagCategory(case.contested[0])
    pets = PetFacts(**case.expected_pets) if case.expected_pets else None
    provider = MockProvider()
    for fire in (True, False, True, False):
        provider.queue(ScreeningReport(
            flags=[ScreeningFlag(category=contested_cat, summary="s", evidence="e")] if fire else [],
            pets=pets or PetFacts(),
        ))
    rep = stability_run(provider, case, screening_model="m", k=4)
    assert rep.marker == "[contested-split]"
    # The reps that FIRED the contested flag read as the divergent 'fail' side; conservative
    # reps read 'pass' — so the split is visible rep-by-rep, not all-'pass'.
    outcomes = [r.outcome for r in rep.runs]
    assert any(o.startswith("fail") for o in outcomes), "a fired-contested rep should token fail"
    assert any(o == "pass" for o in outcomes), "a conservative rep should token pass"


def test_stability_flags_a_changing_flag_set() -> None:
    """The flag SET changing run-to-run is the instability signal: no flags one run,
    an OTHER flag the next → flipped, [UNSTABLE]. Uses a clean case so the flag alone drives
    the grade flip (a pet case would be graded on facts, not the incidental flag)."""
    case = next(
        c for c in load_cases() if not c.fires and not c.absent and c.expected_pets is None
    )
    provider = MockProvider()
    for cats in ([], [FlagCategory.OTHER], [], [FlagCategory.OTHER]):
        provider.queue(ScreeningReport(flags=[
            ScreeningFlag(category=c, summary="s", evidence="e")
            for c in cats
        ]))
    rep = stability_run(provider, case, screening_model="m", k=4)
    assert rep.flipped
    assert rep.marker == "[UNSTABLE]"
