"""Judge-vs-human agreement metrics. The math here decides whether we trust the judge,
so it's tested against hand-computed expectations — a bug would make a bad judge look good."""

from app.ai.schemas import JudgeReport, JudgeVerdict
from app.evals.agreement import score_agreement
from app.evals.judge import JudgeCase, JudgeResult


def _result(*, pass_name: str, expected: JudgeVerdict, verdict: JudgeVerdict,
            contested: bool = False) -> JudgeResult:
    case = JudgeCase(
        key="k", title="t", task="task", evidence={}, expected=expected,
        contested=contested, pass_name=pass_name,
    )
    return JudgeResult(
        case=case, report=JudgeReport(verdict=verdict, reason="r"),
        model_id="m", input_tokens=1, output_tokens=1, cost_usd=0.0,
    )


def test_overall_agreement_and_contested_excluded() -> None:
    results = [
        _result(pass_name="scoring", expected=JudgeVerdict.SUPPORTED, verdict=JudgeVerdict.SUPPORTED),
        _result(pass_name="scoring", expected=JudgeVerdict.UNSUPPORTED, verdict=JudgeVerdict.UNSUPPORTED),
        _result(pass_name="scoring", expected=JudgeVerdict.SUPPORTED, verdict=JudgeVerdict.UNSUPPORTED),  # miss
        # contested: judge disagrees with the leaning, but it must NOT count against agreement
        _result(pass_name="consolidation", expected=JudgeVerdict.MERGE, verdict=JudgeVerdict.KEEP, contested=True),
    ]
    rep = score_agreement(results)
    assert rep.n_total == 4
    assert rep.n_scored == 3          # contested excluded from denominator
    assert rep.n_contested == 1
    assert rep.n_agree == 2
    assert abs(rep.agreement - 2 / 3) < 1e-9


def test_failure_recall_is_the_number_that_matters() -> None:
    # 3 human-labelled problems (unsupported/mismatches/flag_unsupported); judge catches 2.
    results = [
        _result(pass_name="scoring", expected=JudgeVerdict.UNSUPPORTED, verdict=JudgeVerdict.UNSUPPORTED),   # caught
        _result(pass_name="matching", expected=JudgeVerdict.MISMATCHES, verdict=JudgeVerdict.MISMATCHES),    # caught
        _result(pass_name="screening", expected=JudgeVerdict.FLAG_UNSUPPORTED, verdict=JudgeVerdict.FLAG_SUPPORTED),  # MISSED
        _result(pass_name="scoring", expected=JudgeVerdict.SUPPORTED, verdict=JudgeVerdict.SUPPORTED),        # clean, not a problem
    ]
    rep = score_agreement(results)
    assert rep.failure_total == 3
    assert rep.failure_caught == 2
    assert abs(rep.failure_recall - 2 / 3) < 1e-9
    # judge made 2 problem-calls, both correct → precision 1.0
    assert rep.judge_problem_calls == 2
    assert abs(rep.failure_precision - 1.0) < 1e-9


def test_per_category_breakdown() -> None:
    results = [
        _result(pass_name="scoring", expected=JudgeVerdict.SUPPORTED, verdict=JudgeVerdict.SUPPORTED),
        _result(pass_name="scoring", expected=JudgeVerdict.SUPPORTED, verdict=JudgeVerdict.UNSUPPORTED),
        _result(pass_name="screening", expected=JudgeVerdict.FLAG_SUPPORTED, verdict=JudgeVerdict.FLAG_SUPPORTED),
    ]
    rep = score_agreement(results)
    assert rep.per_category["scoring"] == (1, 2)
    assert rep.per_category["screening"] == (1, 1)


def test_kappa_is_chance_corrected_not_raw_agreement() -> None:
    # All-agree across two labels → observed 1.0, kappa 1.0.
    perfect = [
        _result(pass_name="scoring", expected=JudgeVerdict.SUPPORTED, verdict=JudgeVerdict.SUPPORTED),
        _result(pass_name="scoring", expected=JudgeVerdict.UNSUPPORTED, verdict=JudgeVerdict.UNSUPPORTED),
    ]
    assert score_agreement(perfect).kappa == 1.0

    # Single label on both sides → kappa undefined (not a misleading 1.0).
    one_class = [
        _result(pass_name="scoring", expected=JudgeVerdict.SUPPORTED, verdict=JudgeVerdict.SUPPORTED),
        _result(pass_name="scoring", expected=JudgeVerdict.SUPPORTED, verdict=JudgeVerdict.SUPPORTED),
    ]
    assert score_agreement(one_class).kappa is None


def test_no_problem_cases_gives_none_recall() -> None:
    results = [
        _result(pass_name="scoring", expected=JudgeVerdict.SUPPORTED, verdict=JudgeVerdict.SUPPORTED),
    ]
    rep = score_agreement(results)
    assert rep.failure_total == 0
    assert rep.failure_recall is None
