"""Incomplete measurements retain evidence without claiming stable coverage."""

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
