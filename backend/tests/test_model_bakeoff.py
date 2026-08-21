from dataclasses import dataclass

from app.ai.mock_provider import MockProvider
from app.evals.model_bakeoff import (
    MeasuringProvider,
    _outcome,
    _summarize,
    _summarize_cases,
)
from app.evals.model_rank_bakeoff import CONFIGURATIONS, LUNA, TERRA, _reasoning_for


@dataclass
class _Result:
    verdict: str = "merge"


def test_rank_candidate_matches_selected_models_and_reasoning() -> None:
    candidate = CONFIGURATIONS["candidate"]

    assert set(candidate["models"].values()) == {LUNA, TERRA}
    assert candidate["reasoning"] == {LUNA: "low", TERRA: "low"}


def test_rank_reasoning_override_applies_to_each_openai_model() -> None:
    candidate = CONFIGURATIONS["candidate"]

    assert _reasoning_for(candidate, "medium") == {LUNA: "medium", TERRA: "medium"}


def test_outcome_prefers_categorical_verdict() -> None:
    assert _outcome(_Result()) == "merge"


def test_summary_groups_quality_usage_cost_and_latency() -> None:
    rows = [
        {
            "pass": "screening", "model": "model-a", "reasoning_effort": None,
            "passed": True, "outcome": "no_flags", "input_tokens": 10,
            "output_tokens": 2, "cost_usd": 0.1, "elapsed_seconds": 1.5,
        },
        {
            "pass": "screening", "model": "model-a", "reasoning_effort": None,
            "passed": False, "outcome": "error", "input_tokens": 0,
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
        "case": "case-a", "contested": False,
    }
    rows = [
        base | {"passed": True, "outcome": "no_flags"},
        base | {"passed": True, "outcome": "no_flags"},
        base | {"passed": False, "outcome": "internal_inconsistency"},
    ]

    assert _summarize_cases(rows) == [{
        "pass": "screening", "model": "model-a", "reasoning_effort": "low",
        "case": "case-a", "contested": False, "passed": 2, "total": 3,
        "grade_stable": False, "outcome_stable": False,
        "majority_outcome": "no_flags", "majority_agreement": 2 / 3,
        "outcomes": {"no_flags": 2, "internal_inconsistency": 1},
    }]
