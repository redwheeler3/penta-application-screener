"""Judge-vs-human agreement metrics. The math here decides whether we trust the judge,
so it's tested against hand-computed expectations — a bug would make a bad judge look good.

The blind judge reproduces each pass's output and grades it against the human label, yielding a
uniform outcome per case (agrees / human_is_problem / judge_is_problem + compact label tokens).
These build that outcome directly (no model), which is exactly what score_agreement consumes."""

from app.evals.agreement import score_agreement
from app.evals.judge import JudgeCase, JudgeResult
from app.evals.reproduce import Reproduced


def _result(*, pass_name: str, human: str, judge: str, agrees: bool,
            human_problem: bool = False, judge_problem: bool = False,
            contested: bool = False) -> JudgeResult:
    case = JudgeCase(
        key="k", pass_name=pass_name, given={}, expected=human,
        background="", contested=contested,
    )
    rep = Reproduced(
        judge_label=judge, human_label=human, agrees=agrees,
        human_is_problem=human_problem, judge_is_problem=judge_problem,
        detail="r", cost_usd=0.0,
    )
    return JudgeResult(case=case, reproduced=rep, model_id="m")


def test_overall_agreement_and_contested_excluded() -> None:
    results = [
        _result(pass_name="scoring", human="in-band", judge="in-band", agrees=True),
        _result(pass_name="scoring", human="out", judge="out", agrees=True),
        _result(pass_name="scoring", human="in-band", judge="out", agrees=False),  # miss
        # contested: judge disagrees with the leaning, but it must NOT count against agreement
        _result(pass_name="consolidation", human="merge", judge="keep", agrees=False, contested=True),
    ]
    rep = score_agreement(results)
    assert rep.n_total == 4
    assert rep.n_scored == 3          # contested excluded from denominator
    assert rep.n_contested == 1
    assert rep.n_agree == 2
    assert abs(rep.agreement - 2 / 3) < 1e-9


def test_failure_recall_is_the_number_that_matters() -> None:
    # 3 human-labelled problems; judge catches 2.
    results = [
        _result(pass_name="matching", human="mismatches", judge="mismatches", agrees=True,
                human_problem=True, judge_problem=True),   # caught
        _result(pass_name="screening", human="fires: x", judge="fires: x", agrees=True,
                human_problem=True, judge_problem=True),   # caught
        _result(pass_name="screening", human="fires: y", judge="no flags", agrees=False,
                human_problem=True, judge_problem=False),  # MISSED
        _result(pass_name="matching", human="matches", judge="matches", agrees=True),  # clean
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
        _result(pass_name="scoring", human="in-band", judge="in-band", agrees=True),
        _result(pass_name="scoring", human="in-band", judge="out", agrees=False),
        _result(pass_name="screening", human="clean", judge="clean", agrees=True),
    ]
    rep = score_agreement(results)
    assert rep.per_category["scoring"] == (1, 2)
    assert rep.per_category["screening"] == (1, 1)


def test_kappa_is_chance_corrected_not_raw_agreement() -> None:
    # All-agree across two labels → observed 1.0, kappa 1.0.
    perfect = [
        _result(pass_name="consolidation", human="merge", judge="merge", agrees=True),
        _result(pass_name="consolidation", human="keep", judge="keep", agrees=True),
    ]
    assert score_agreement(perfect).kappa == 1.0

    # Single label on both sides → kappa undefined (not a misleading 1.0).
    one_class = [
        _result(pass_name="consolidation", human="merge", judge="merge", agrees=True),
        _result(pass_name="consolidation", human="merge", judge="merge", agrees=True),
    ]
    assert score_agreement(one_class).kappa is None


def test_no_problem_cases_gives_none_recall() -> None:
    results = [
        _result(pass_name="scoring", human="in-band", judge="in-band", agrees=True),
    ]
    rep = score_agreement(results)
    assert rep.failure_total == 0
    assert rep.failure_recall is None
