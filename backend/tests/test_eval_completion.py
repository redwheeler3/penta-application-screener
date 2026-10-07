"""Incomplete measurements retain evidence without claiming stable coverage."""

import copy
import time
from dataclasses import replace
from threading import Event, Lock

import pytest
from httpx import ASGITransport, AsyncClient

from app.ai.mock_provider import MockProvider
from app.ai.schemas import ConsolidationReport, JudgeReport, JudgeVerdict
from app.core.work_cancellation import WorkCancelled, cancellation_scope
from app.evals import consolidate, judge
from app.evals.stability import RunDetail, run_stability
from tests.test_evals_api import _stream_events, setup_app


@pytest.mark.parametrize("successes", [0, 1, 4, 5])
def test_every_stability_attempt_survives_partial_failure(successes):
    lock = Lock()
    attempts = 0
    def call():
        nonlocal attempts
        with lock:
            attempts += 1
            number = attempts
        if number > successes:
            raise TimeoutError("Synthetic timeout")
        return RunDetail("pass", "Synthetic output")
    report = run_stability(call, k=5)
    assert attempts == 5
    assert len(report.runs) == 5
    assert sum(run.error is None for run in report.runs) == successes
    if successes == 5:
        assert report.marker == "[stable]"
        assert report.agreement == 1
    else:
        assert report.marker == "[incomplete]"
        assert report.agreement is None
        assert report.majority is None
        assert report.flipped is None
        assert report.tally["error"] == 5 - successes


def test_repetition_order_and_error_details_follow_submission_order(monkeypatch):
    from app.ai import analysis
    monkeypatch.setattr(analysis, "run_in_pool", lambda *_args, **_kwargs: iter([
        (2, RunDetail("pass", "Third"), None), (0, RunDetail("pass", "First"), None),
        (1, None, TimeoutError("Second")),
    ]))
    report = run_stability(lambda: RunDetail("unused"), k=3)
    assert [run.detail for run in report.runs] == ["First", "TimeoutError: Second", "Third"]


def test_consistently_wrong_valid_answers_are_stable_but_cancellation_is_not_a_result():
    report = run_stability(lambda: RunDetail("fail", "Outside expected band"), k=3)
    assert report.complete
    assert report.marker == "[stable]"
    cancelled = Event()
    cancelled.set()
    with cancellation_scope(cancelled), pytest.raises(WorkCancelled):
        run_stability(lambda: RunDetail("pass"), k=3)


def test_contested_case_requires_an_actual_verdict():
    case = replace(consolidate.load_cases()[0], contested=True)
    provider = MockProvider()
    provider.route("", ConsolidationReport(verdicts=[]))
    result = consolidate.run_case(provider, case, consolidate_model="mock-model")
    assert not result.passed
    assert result.error
    report = consolidate.stability_run(provider, case, consolidate_model="mock-model", k=3)
    assert report.marker == "[incomplete]"
    assert report.tally == {"error": 3}
    blind = replace(next(c for c in judge.load_cases() if c.pass_name == "consolidation"), contested=True)
    provider = MockProvider()
    provider.route("", JudgeReport(verdict=JudgeVerdict.MATCHES, reason="Wrong vocabulary"))
    result = judge.judge_case(provider, blind, model_id="mock-model")
    assert result.marker == "[error]"
    assert result.reproduced.error


@pytest.mark.anyio
async def test_incomplete_judge_stability_keeps_success_and_errors_in_live_and_saved_results():
    case = next(c for c in judge.load_cases() if c.pass_name == "consolidation")
    app, _db, provider = setup_app()
    provider.queue(JudgeReport(verdict=JudgeVerdict(case.expected), reason="Synthetic success"))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        events = await _stream_events(client, f"/evals/judge?mode=stability&k=5&case={case.key}&passName=consolidation")
        summary = next(event for event in events if event["type"] == "summary")
        outcome = summary["result"]["cases"][0]
        saved = (await client.get("/evals/last-run?keys=stability")).json()["runs"][0]["result"]["cases"][0]
    assert saved == outcome
    assert outcome["marker"] == "[incomplete]"
    assert outcome["agreement"] is None
    assert len(outcome["runs"]) == 5
    assert sum(run["error"] is not None for run in outcome["runs"]) == 4
    assert any(run["detail"] == "Synthetic success" for run in outcome["runs"])


@pytest.mark.anyio
async def test_contested_missing_verdict_is_not_counted_as_passed_in_live_or_history():
    case = next(c for c in consolidate.load_cases() if c.contested)
    app, _db, provider = setup_app()
    provider.route("", ConsolidationReport(verdicts=[]))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        events = await _stream_events(client, f"/evals/consolidation?case={case.key}")
        result = next(e for e in events if e["type"] == "summary")["result"]
        saved = (await client.get("/evals/last-run?keys=consolidation")).json()["runs"][0]["result"]
    assert result["passed"] == 0
    assert saved["passed"] == 0
    assert result["cases"][0]["error"]


@pytest.mark.parametrize("error_first", [False, True])
def test_case_collection_preserves_both_completion_orders_and_narration(error_first):
    from app.api.evals._shared import over_cases

    finished = Event()
    narration = []
    first = "error" if error_first else "success"
    def flush(text):
        narration.append(text)
        if text == f"Started {first}":
            finished.set()
    def one(case, delta):
        delta(f"Started {case}")
        if case != first:
            assert finished.wait(2)
        if case == "error":
            raise TimeoutError("Synthetic timeout")
        return case
    result = over_cases(["success", "error"], one, on_delta=flush,
        max_workers=2, on_error=lambda case, error: (case, error))
    assert result == ["success", ("error", "TimeoutError: Synthetic timeout")]
    assert "Started error" in narration
    assert "Started success" in narration
    assert narration[0] == f"Started {first}"


@pytest.mark.parametrize("family", ["scoring", "screening", "matching", "consolidation", "decomposition", "judge"])
@pytest.mark.parametrize("successes", [0, 1])
@pytest.mark.anyio
async def test_ordinary_partial_batch_persists_every_case(monkeypatch, family, successes):
    from app.ai.provider import AIResult, Usage
    from app.ai.schemas import (
        DimensionMatchReport,
        DimensionScore,
        DimensionScoringReport,
        ScreeningReport,
    )
    from app.api.evals import _categorical, runs
    from app.evals import decompose, scoring
    from app.evals.dataset import DatasetSnapshot, load_dataset
    from app.schemas.settings import AppSettings
    from app.services.settings import save_app_settings
    from tests.test_consolidate_eval import _mock_confirm
    from tests.test_decompose_eval import _mock_merge

    source_family = "consolidation" if family == "judge" else family
    data = copy.deepcopy(load_dataset(source_family).families[source_family])
    data["cases"] = [copy.deepcopy(data["cases"][0]) for _ in range(2)]
    for i, case in enumerate(data["cases"]):
        case["key"] = f"synthetic-{i}"
        case["metadata"]["contested"] = True
    families = {source_family: data}
    if family == "judge":
        families = copy.deepcopy(load_dataset().families)
        for contents in families.values():
            contents["cases"] = []
        families[source_family] = data
    snapshot = DatasetSnapshot(families)
    monkeypatch.setattr(runs, "load_dataset", lambda *_: snapshot)
    monkeypatch.setattr(_categorical, "load_dataset", lambda *_: snapshot)
    from app.api.evals import catalog
    monkeypatch.setattr(catalog, "load_dataset", lambda *_: snapshot)
    app, db, provider = setup_app()
    settings = AppSettings()
    settings.ai.max_workers = 1
    save_app_settings(db, settings)
    if family == "scoring":
        case = scoring.load_golden(data=data)[0]
        output = DimensionScoringReport(scores=[DimensionScore(dimension_key=case.dimension.key,
            score=0, confidence="low", rationale="Synthetic", evidence="Synthetic")])
    elif family == "screening":
        output = ScreeningReport()
    elif family == "matching":
        output = DimensionMatchReport(matches=[])
    elif family == "judge":
        output = JudgeReport(verdict=JudgeVerdict.KEEP, reason="Synthetic")
    elif family == "consolidation":
        output = next(iter(_mock_confirm(consolidate.load_cases(data=data)[0], same_concept=False).routed.values())).output
    else:
        output = next(iter(_mock_merge(decompose.load_cases(data=data)[0]).routed.values())).output
    attempts = 0
    def call(**kwargs):
        nonlocal attempts
        attempts += 1
        if attempts > successes:
            raise TimeoutError("Synthetic timeout")
        return AIResult(output=output, usage=Usage(100, 20), model_id=kwargs["model_id"])
    monkeypatch.setattr(provider, "structured_output", call)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        events = await _stream_events(client, f"/evals/{family}")
        result = next(event for event in events if event["type"] == "summary")["result"]
        saved = (await client.get(f"/evals/last-run?keys={family}")).json()["runs"][0]["result"]
    assert attempts == 2
    assert len(result["cases"]) == 2
    assert sum(case["error"] is None for case in result["cases"]) == successes
    assert saved["cases"] == result["cases"]
    assert all(not case.get("passed") for case in result["cases"] if case["error"])


@pytest.mark.parametrize(("limit", "k", "cases"), [(1, 5, 2), (3, 5, 2), (10, 5, 3)])
def test_nested_repetition_budget_retains_all_attempts(limit, k, cases):
    from app.api.evals._shared import case_workers, over_cases
    from app.schemas.settings import AppSettings

    settings = AppSettings()
    settings.ai.max_workers = limit
    lock = Lock()
    active = peak = attempts = 0
    def repeat():
        nonlocal active, peak, attempts
        with lock:
            attempts += 1
            number = attempts
            active += 1
            peak = max(peak, active)
        time.sleep(0.01)
        with lock:
            active -= 1
        if number % 4 == 0:
            raise TimeoutError("Synthetic bounded attempt failure")
        return RunDetail("pass")
    results = over_cases(list(range(cases)), lambda _case, delta: run_stability(
        repeat, k=k, max_workers=min(k, limit), on_delta=delta), on_delta=lambda _: None,
        max_workers=case_workers(settings, fan_out=k))
    assert attempts == cases * k
    assert sum(len(report.runs) for report in results) == attempts
    assert sum(run.error is not None for report in results for run in report.runs) == attempts // 4
    assert peak <= limit
    assert peak >= min(k, limit)


def test_case_recovery_does_not_catch_cancellation_or_missing_output():
    from app.api.evals._shared import over_cases
    cancelled = Event()
    cancelled.set()
    with cancellation_scope(cancelled), pytest.raises(WorkCancelled):
        over_cases([1], lambda *_: None, on_delta=lambda _: None, max_workers=1,
            on_error=lambda *_: pytest.fail("Cancellation became a result"))
    result = over_cases([1], lambda *_: None, on_delta=lambda _: None, max_workers=1,
        on_error=lambda _case, error: error)
    assert result == ["RuntimeError: Eval case returned no outcome"]


@pytest.mark.anyio
@pytest.mark.parametrize("family", ["scoring", "judge"])
async def test_empty_ordinary_batch_has_no_results_or_provider_calls(monkeypatch, family):
    from app.api.evals import runs
    from app.evals.dataset import load_dataset
    snapshot = load_dataset()
    for data in snapshot.families.values():
        data["cases"] = []
    monkeypatch.setattr(runs, "load_dataset", lambda *_: snapshot)
    app, _db, provider = setup_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        events = await _stream_events(client, f"/evals/{family}")
    result = events[-1]["result"]
    assert result["cases"] == []
    if family == "scoring":
        assert result["passed"] == result["total"] == 0
    assert provider.calls == []
