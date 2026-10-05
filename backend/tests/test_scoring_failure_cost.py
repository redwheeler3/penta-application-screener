"""Known usage survives incomplete scoring; failed applicants never count as scored."""

import pytest
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import select

from app.ai.dimension_scoring import MAX_SCORING_RETRIES, score_dimensions
from app.ai.pricing import cost_usd
from app.ai.provider import AIResult, Usage
from app.ai.schemas import DimensionScoringReport
from app.db.models import ApplicationAIResult, User, UserRole
from app.schemas.settings import AppSettings
from app.services.ranking.analysis import create_analysis
from app.services.ranking.pipeline import ScoreTally
from tests.application_support import current_opening_id
from tests.ranking_support import (
    a_pattern_report,
    a_scoring_report,
    add_eligible,
    setup_app,
    stream_events,
)


@pytest.mark.anyio
@pytest.mark.parametrize("mixed", [False, True])
async def test_incomplete_retries_keep_usage_and_only_successes_count_as_scored(mixed) -> None:
    app, db, provider = setup_app(UserRole.MEMBER)
    failed_applicant = add_eligible(db, email="incomplete@example.com", raw_hash="incomplete")
    if mixed:
        add_eligible(db, email="complete@example.com", raw_hash="complete")
    report, settings = a_pattern_report(), AppSettings()
    create_analysis(db, user=db.scalar(select(User)), opening_id=current_opening_id(db),
        report=report, narrative=None, inputs_fingerprint="synthetic")
    model = settings.ai.dimension_scoring_model
    incomplete = DimensionScoringReport(scores=[a_scoring_report().scores[0]])
    provider.route(f'"applicant_id": {failed_applicant.id}', incomplete,
        model_id=model, input_tokens=1000, output_tokens=200)
    provider.route("applicant_id", a_scoring_report(), model_id=model, input_tokens=1000, output_tokens=200)
    known_calls = MAX_SCORING_RETRIES + 1 + int(mixed)
    expected_cost = known_calls * cost_usd(model, Usage(input_tokens=1000, output_tokens=200))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        events = await stream_events(client, "/ranking/score-current")
        summary = events[-1]
        assert summary["scored"] == int(mixed)
        assert summary["failed"] == 1
        assert summary["totalCostUsd"] == pytest.approx(expected_cost)
        progress = [event for event in events if event["type"] == "progress"]
        assert progress[-1]["processed"] == 1 + int(mixed)
        ledger = (await client.get("/observability/last-runs")).json()["rankScores"]
        charged = ledger["passes"][0]
        assert charged["inputTokens"] == known_calls * 1000
        assert charged["outputTokens"] == known_calls * 200
        assert charged["freshUsd"] == pytest.approx(expected_cost)
        assert charged["freshCalls"] == known_calls
        assert ledger["freshUsd"] == pytest.approx(expected_cost)
    assert len(provider.calls) == known_calls
    assert db.scalar(select(ApplicationAIResult).where(ApplicationAIResult.producer_application_id == failed_applicant.id)) is None


@pytest.mark.parametrize("completed_reply", [False, True])
def test_provider_failure_retains_only_returned_usage_and_original_error_type(monkeypatch, caplog, completed_reply) -> None:
    _app, db, provider = setup_app(UserRole.MEMBER)
    application = add_eligible(db, email="synthetic@example.com", raw_hash="synthetic")
    report, settings = a_pattern_report(), AppSettings()
    attempts = []

    def fail_after_partial(**kwargs):
        attempts.append(True)
        if completed_reply and len(attempts) == 1:
            return AIResult(output=DimensionScoringReport(scores=[a_scoring_report().scores[0]]),
                usage=Usage(input_tokens=1000, output_tokens=200), model_id=kwargs["model_id"])
        raise TimeoutError("synthetic-sensitive-provider-output")

    monkeypatch.setattr(provider, "structured_output", fail_after_partial)
    result = next(score_dimensions(db, provider, applications=[application], report=report,
        settings=settings, max_workers=1))
    assert result.failed
    assert result.error_type == "TimeoutError"
    assert "synthetic-sensitive-provider-output" not in caplog.text
    assert result.failure_cost.calls == int(completed_reply)
    assert result.failure_cost.input_tokens == 1000 * int(completed_reply)
    assert result.failure_cost.output_tokens == 200 * int(completed_reply)
    assert result.failure_cost.cost_usd == pytest.approx(
        cost_usd(settings.ai.dimension_scoring_model, Usage(input_tokens=1000, output_tokens=200)) * int(completed_reply))
    assert db.scalar(select(ApplicationAIResult)) is None


def test_complete_batch_uses_whole_call_price_even_when_token_shares_round_down() -> None:
    _app, db, provider = setup_app(UserRole.MEMBER)
    application = add_eligible(db, email="synthetic@example.com", raw_hash="synthetic")
    settings = AppSettings()
    provider.queue(a_scoring_report(), model_id=settings.ai.dimension_scoring_model,
        input_tokens=1001, output_tokens=201)
    result = next(score_dimensions(db, provider, applications=[application], report=a_pattern_report(),
        settings=settings, max_workers=1))
    assert result.outcome.cost_usd == pytest.approx(cost_usd(settings.ai.dimension_scoring_model,
        Usage(input_tokens=1001, output_tokens=201)))
    assert result.outcome.input_tokens == 1001
    assert result.outcome.output_tokens == 201
    assert result.fresh_calls == 1


def test_successful_reasks_count_completed_replies_separately_from_dimensions() -> None:
    _app, db, provider = setup_app(UserRole.MEMBER)
    application = add_eligible(db, email="synthetic@example.com", raw_hash="synthetic")
    report, settings = a_pattern_report(), AppSettings()
    report.dimensions.append(report.dimensions[0].model_copy(update={"key": "third"}))
    base = a_scoring_report().scores
    provider.queue(DimensionScoringReport(scores=[base[0]]), model_id=settings.ai.dimension_scoring_model,
        input_tokens=1000, output_tokens=200)
    provider.queue(DimensionScoringReport(scores=[base[1], base[0].model_copy(update={"dimension_key": "third"})]),
        model_id=settings.ai.dimension_scoring_model, input_tokens=1000, output_tokens=200)
    result = next(score_dimensions(db, provider, applications=[application], report=report,
        settings=settings, max_workers=1))
    tally = ScoreTally()
    tally.add(result)
    measured = tally.as_pass_cost(settings.ai.dimension_scoring_model)
    assert result.fresh_units == 3
    assert measured.calls == len(provider.calls) == 2
    assert measured.input_tokens == 2000
    assert measured.output_tokens == 400
