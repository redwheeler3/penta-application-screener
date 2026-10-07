"""Identical outputs must be graded identically by live and blind consumers."""

import pytest

from app.ai.mock_provider import MockProvider
from app.ai.schemas import (
    DimensionScore,
    DimensionScoringReport,
    PetFacts,
    ScreeningFlag,
    ScreeningReport,
)
from app.evals import judge, scoring, screening
from app.evals.case_schema import CaseValidationError, validate_case
from app.evals.dataset import DatasetSnapshot, case_input_fingerprint


@pytest.mark.parametrize(("expected", "categories", "pets", "passes"), [
    ({"fires": "fake_contact|minimal_essay"}, ["fake_contact"], {}, True),
    ({"fires": ["fake_contact | minimal_essay"]}, ["minimal_essay"], {}, True),
    ({"fires": [["fake_contact", "minimal_essay"]]}, ["fake_contact"], {}, True),
    ({"fires": ["fake_contact"]}, [], {}, False),
    ({"absent": ["fake_contact"]}, ["fake_contact"], {}, False),
    ({"pets": {"dogs": 2, "cats": 1}}, [], {"dogs": 2, "cats": 1}, True),
    ({"pets": {"dogs": 2, "cats": 1}}, [], {}, False),
    ({"pets": {"other_pets": ["rabbit"]}}, [], {"other_pets": ["pet rabbit"]}, True),
    ({"pets": {"other_pets": ["rabbit"]}}, [], {}, False),
    ({}, [], {}, True),
    ({}, ["fake_contact"], {}, False),
])
def test_screening_consumers_apply_the_same_expectations(expected, categories, pets, passes):
    raw = {"key": "synthetic", "given": {"fields": {}, "essays": {}}, "metadata": {"expected": expected}}
    data = {"cases": [raw], "judge_background": "Synthetic blind brief"}
    live = screening.load_cases(data=data)[0]
    blind = judge.load_cases(DatasetSnapshot({"screening": data}))[0]
    provider = MockProvider()
    provider.route("", ScreeningReport(flags=[ScreeningFlag(category=c, summary="Synthetic", evidence="Synthetic")
        for c in categories], pets=PetFacts(**pets)))
    assert screening.run_case(provider, live, screening_model="mock-model").passed == passes
    assert judge.judge_case(provider, blind, model_id="mock-model").agrees_with_label == passes
    assert len(provider.calls) == 2
    assert '"expected"' not in provider.calls[-1].prompt


@pytest.mark.parametrize("returned_key", ["requested", "unrelated", None])
def test_scoring_consumers_require_the_requested_dimension(returned_key):
    given = {"applicant": {"facts": {}, "essays": {}}, "dimension": {
        "key": "requested", "name": "Synthetic", "definition": "Synthetic", "high_end": "High", "low_end": "Low"}}
    expected = {"score_min": 0.5, "score_max": 1}
    data = {"cases": [{"key": "case", "given": given, "metadata": {"expected": expected}}], "judge_background": "Synthetic"}
    provider = MockProvider()
    scores = [] if returned_key is None else [DimensionScore(dimension_key=returned_key, score=0.8,
        confidence="high", rationale="Synthetic", evidence="Synthetic")]
    provider.route("", DimensionScoringReport(scores=scores))
    live = scoring.load_golden(data=data)[0]
    blind = judge.load_cases(DatasetSnapshot({"scoring": data}))[0]
    assert scoring.run_case(provider, live, scoring_model="mock-model").passed == (returned_key == "requested")
    assert judge.judge_case(provider, blind, model_id="mock-model").agrees_with_label == (returned_key == "requested")


def test_contested_policy_has_one_location_for_both_consumers():
    raw = {"key": "synthetic", "given": {"fields": {}, "essays": {}},
        "metadata": {"expected": {"fires": []}, "contested": True}}
    data = {"cases": [raw], "judge_background": "Synthetic"}
    assert screening.load_cases(data=data)[0].contested
    assert judge.load_cases(DatasetSnapshot({"screening": data}))[0].contested
    raw["metadata"]["expected"]["contested"] = True
    with pytest.raises(CaseValidationError, match="put contested in metadata"):
        validate_case("screening", raw)


def test_eval_grading_revision_expires_eval_coverage_only(monkeypatch):
    from app.ai.analysis import cache_key
    from app.db.models import Application
    from app.evals import dataset
    from app.schemas.settings import AppSettings
    raw = {"given": {}, "metadata": {"expected": "keep"}}
    application = Application(raw_row_hash="synthetic", normalized={})
    model = AppSettings().ai.screening_model
    production = cache_key(application=application, kind="screening", model_id=model, prompt_version="unchanged")
    previous = case_input_fingerprint(raw)
    monkeypatch.setattr(dataset, "GRADING_VERSION", dataset.GRADING_VERSION + 1)
    assert case_input_fingerprint(raw) != previous
    assert cache_key(application=application, kind="screening", model_id=model, prompt_version="unchanged") == production
