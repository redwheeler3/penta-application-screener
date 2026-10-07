from dataclasses import dataclass, replace

import pytest

from app.ai.mock_provider import MockProvider
from app.ai.model_catalog import MODEL_IDS_BY_ROUTE
from app.evals.model_bakeoff import (
    MeasuringProvider,
    _outcome,
    _summarize,
    _summarize_cases,
)
from app.evals.model_rank_bakeoff import CONFIGURATIONS, _reasoning_for


@dataclass
class _Result:
    verdict: str = "merge"


def test_rank_candidate_matches_selected_models_and_reasoning() -> None:
    candidate = CONFIGURATIONS["direct-candidate"]
    luna = MODEL_IDS_BY_ROUTE["direct"]["luna"]
    terra = MODEL_IDS_BY_ROUTE["direct"]["terra"]

    assert set(candidate["models"].values()) == {luna, terra}
    assert candidate["reasoning"] == {luna: "low", terra: "low"}


def test_rank_reasoning_override_applies_to_each_openai_model() -> None:
    candidate = CONFIGURATIONS["direct-candidate"]
    luna = MODEL_IDS_BY_ROUTE["direct"]["luna"]
    terra = MODEL_IDS_BY_ROUTE["direct"]["terra"]

    assert _reasoning_for(candidate, "medium") == {
        luna: "medium", terra: "medium"
    }


def test_outcome_prefers_categorical_verdict() -> None:
    assert _outcome(_Result()) == "merge"


def test_summary_groups_quality_usage_cost_and_latency() -> None:
    rows = [
        {
            "pass": "screening", "model": "model-a", "reasoning_effort": None,
            "passed": True, "error": None, "outcome": "no_flags", "input_tokens": 10,
            "output_tokens": 2, "cost_usd": 0.1, "elapsed_seconds": 1.5,
        },
        {
            "pass": "screening", "model": "model-a", "reasoning_effort": None,
            "passed": False, "error": "timeout", "outcome": "error", "input_tokens": 0,
            "output_tokens": 0, "cost_usd": 0.0, "elapsed_seconds": 0.5,
        },
    ]

    assert _summarize(rows) == [{
        "pass": "screening", "model": "model-a", "reasoning_effort": None,
        "passed": 1, "total": 2, "errors": 1, "input_tokens": 10,
        "output_tokens": 2, "cost_usd": 0.1, "call_seconds": 2.0,
    }]


def test_measuring_provider_records_delegated_results() -> None:
    provider = MockProvider()
    measured = MeasuringProvider(provider)
    assert measured.results == []


def test_case_summary_reports_majority_and_instability() -> None:
    base = {
        "pass": "screening", "model": "model-a", "reasoning_effort": "low",
        "case": "case-a", "contested": False, "error": None,
    }
    rows = [
        base | {"passed": True, "outcome": "no_flags"},
        base | {"passed": True, "outcome": "no_flags"},
        base | {"passed": False, "outcome": "internal_inconsistency"},
    ]

    assert _summarize_cases(rows) == [{
        "pass": "screening", "model": "model-a", "reasoning_effort": "low",
        "case": "case-a", "contested": False, "passed": 2, "total": 3,
        "complete": True, "grade_stable": False, "outcome_stable": False,
        "majority_outcome": "no_flags", "majority_agreement": 2 / 3,
        "outcomes": {"no_flags": 2, "internal_inconsistency": 1},
    }]


@pytest.mark.parametrize("invalid", [False, True])
def test_actual_contested_runner_obeys_validity_before_bakeoff_summary(invalid):
    from app.ai.schemas import ConsolidationReport
    from app.evals import consolidate, model_bakeoff
    from tests.test_consolidate_eval import _mock_confirm

    case = replace(consolidate.load_cases()[0], contested=True, expected="merge")
    provider = _mock_confirm(case, same_concept=False)
    if invalid:
        provider = MockProvider()
        provider.route("", ConsolidationReport(verdicts=[]))
    row = model_bakeoff._run_one(provider, model_bakeoff.PASS_SPECS["consolidation"],
        MODEL_IDS_BY_ROUTE["direct"]["terra"], case, 1, "low")
    assert row["passed"] is (not invalid)
    summary = _summarize_cases([row])[0]
    assert summary["complete"] is (not invalid)
    assert summary["outcome_stable"] is (None if invalid else True)


@pytest.mark.parametrize("successes", [0, 1, 3])
def test_bakeoff_error_repeats_cannot_establish_stability(successes):
    from app.ai.schemas import ScreeningReport
    from app.evals import model_bakeoff, screening
    spec = model_bakeoff.PASS_SPECS["screening"]
    provider = MockProvider()
    for _ in range(successes):
        provider.queue(ScreeningReport())
    rows = [model_bakeoff._run_one(provider, spec, MODEL_IDS_BY_ROUTE["direct"]["luna"],
        screening.load_cases()[0], i, "low") for i in range(3)]
    result = _summarize_cases(rows)[0]
    assert result["complete"] is (successes == 3)
    assert result["grade_stable"] is (True if successes == 3 else None)
    assert result["majority_agreement"] == (1 if successes == 3 else None)


@pytest.mark.parametrize("grade_raises", [False, True])
def test_missing_score_or_later_grader_error_keeps_known_usage(grade_raises):
    from app.ai.schemas import DimensionScoringReport
    from app.evals import model_bakeoff, scoring
    model = MODEL_IDS_BY_ROUTE["direct"]["luna"]
    provider = MockProvider()
    provider.route("", DimensionScoringReport(scores=[]), model_id=model, input_tokens=100, output_tokens=20)
    spec = model_bakeoff.PASS_SPECS["scoring"]
    if grade_raises:
        def run(provider, case, model):
            scoring.run_case(provider, case, scoring_model=model)
            raise RuntimeError("Synthetic grader failure")
        spec = replace(spec, run=run)
    row = model_bakeoff._run_one(provider, spec, model, scoring.load_golden()[0], 1, "low")
    assert not row["passed"]
    assert row["error"]
    assert row["calls"] == 1
    assert (row["input_tokens"], row["output_tokens"]) == (100, 20)
    assert row["cost_usd"] > 0
    assert not _summarize_cases([row])[0]["complete"]


def test_bakeoff_captures_family_once_for_all_models_and_repetitions(monkeypatch):
    from app.ai.schemas import ScreeningReport
    from app.evals import model_bakeoff, screening
    reads = []
    case = screening.load_cases()[0]
    def changing_source():
        reads.append(1)
        return (replace(case, key=f"version-{len(reads)}"),)
    provider = MockProvider()
    provider.route("", ScreeningReport())
    monkeypatch.setattr(model_bakeoff, "StrandsProvider", lambda **_: provider)
    monkeypatch.setitem(model_bakeoff.PASS_SPECS, "screening",
        replace(model_bakeoff.PASS_SPECS["screening"], load=changing_source))
    report = model_bakeoff.run_bakeoff(route="direct", region="us-east-1",
        pass_names=["screening"], repeats=3, progress=lambda _: None)
    assert len(reads) == 1
    assert len(report["results"]) == 6
    assert {row["case"] for row in report["results"]} == {"version-1"}


def test_empty_bakeoff_is_explicitly_no_cases(monkeypatch):
    from app.evals import model_bakeoff
    monkeypatch.setattr(model_bakeoff, "StrandsProvider", lambda **_: MockProvider())
    monkeypatch.setitem(model_bakeoff.PASS_SPECS, "screening",
        replace(model_bakeoff.PASS_SPECS["screening"], load=lambda: ()))
    report = model_bakeoff.run_bakeoff(route="direct", region="us-east-1",
        pass_names=["screening"], repeats=3, progress=lambda _: None)
    assert report["status"] == "no_cases"
    assert report["results"] == report["case_summary"] == []
