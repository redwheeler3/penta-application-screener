"""Failed phases retain returned usage without creating a false completion or cost estimate."""

from dataclasses import replace

import pytest
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import select

from app.ai.pricing import cost_usd
from app.ai.provider import Usage
from app.ai.schemas import ConsolidationReport
from app.db.models import Analysis, ApplicationAIResult, RunCostLedger, User, UserRole
from app.schemas.settings import AppSettings
from app.services.cost_report import project_pass_cost_from_history
from app.services.ranking import criteria, pipeline
from app.services.ranking.analysis import create_analysis
from tests.application_support import current_opening_id
from tests.ranking_support import (
    a_pattern_report,
    a_scoring_report,
    add_eligible,
    route_criteria,
    setup_app,
    stream_events,
)


@pytest.mark.anyio
@pytest.mark.parametrize("failure", ["decomposition", "validation", "matching", "criteria storage", "scoring storage", "consolidation"])
async def test_known_pass_costs_survive_later_failures(monkeypatch, caplog, failure) -> None:
    app, db, provider = setup_app(UserRole.ADMIN)
    add_eligible(db, email="synthetic@example.com", raw_hash="synthetic")
    opening_id = current_opening_id(db)
    route_criteria(provider, a_pattern_report())
    provider.route("applicant_id", a_scoring_report())
    settings = AppSettings().ai
    routes = {"<applicant_pool>": settings.discovery_model, "<discovery_reports>": settings.decompose_model,
        "<candidate_pairs>": settings.consolidate_model, "applicant_id": settings.dimension_scoring_model}
    provider.routed = {key: replace(value, usage=Usage(input_tokens=1000, output_tokens=200), model_id=routes[key])
        for key, value in provider.routed.items()}
    original = provider.structured_output
    prior_id = None
    if failure == "matching":
        prior_id = create_analysis(db, user=db.scalar(select(User)), opening_id=opening_id,
            report=a_pattern_report(), narrative=None, inputs_fingerprint="prior").id

    def fail_model(**kwargs):
        name = kwargs["schema"].__name__
        if (failure == "decomposition" and name == "DecompositionReport") or (failure == "matching" and name == "DimensionMatchReport"):
            raise RuntimeError("synthetic-sensitive-provider-output")
        return original(**kwargs)

    monkeypatch.setattr(provider, "structured_output", fail_model)

    def validation_failure(*_args, **_kwargs):
        raise ValueError("Synthetic processing failure")

    if failure == "validation":
        monkeypatch.setattr(criteria, "to_pool_report", validation_failure)
    if failure == "scoring storage":
        monkeypatch.setattr("app.ai.dimension_scoring.stage_result", validation_failure)
    if failure == "criteria storage":
        monkeypatch.setattr(pipeline, "create_analysis", validation_failure)
    if failure == "consolidation":
        def fail_after_reply(measured, *, settings, **kwargs):
            measured.structured_output(model_id=settings.ai.consolidate_model, schema=ConsolidationReport,
                prompt="<candidate_pairs>Synthetic</candidate_pairs>")
            raise ValueError("Synthetic consolidation processing failure")

        monkeypatch.setattr(pipeline, "consolidate_dimensions", fail_after_reply)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        events = await stream_events(client, "/ranking/run")
        last = (await client.get("/observability/last-runs")).json()["rank"]
        totals = (await client.get("/observability/cost")).json()
        metrics = (await client.get("/observability/metrics")).json()
    expected = sum(cost_usd(call.model_id, Usage(input_tokens=1000, output_tokens=200)) for call in provider.calls)
    assert "synthetic-sensitive-provider-output" not in caplog.text
    assert all(record.exc_info is None for record in caplog.records if record.name == "app.ai")
    assert last["freshUsd"] == pytest.approx(expected)
    assert totals["totalCostUsd"] == pytest.approx(expected)
    assert sum(p["inputTokens"] for p in last["passes"]) == 1000 * len(provider.calls)
    assert len(db.scalars(select(RunCostLedger)).all()) == 1
    if failure == "consolidation":
        assert last["status"] == "completed"
        assert events[-1]["type"] == "summary"
        assert any(event["type"] == "warning" for event in events)
        assert metrics["runs"][0]["failedCalls"] == 1
    else:
        assert last["status"] == "failed"
        assert events[-1]["type"] == "error"
        assert not any(event["type"] == "summary" for event in events)
        assert last["failedPass"] == {"decomposition": "Dimension decomposition", "validation": "Dimension decomposition",
            "matching": "Dimension matching", "criteria storage": "Criteria persistence", "scoring storage": "Dimension scoring"}[failure]
        assert metrics["runs"][0]["status"] == "failed"
        assert project_pass_cost_from_history(db, opening_id, "Pattern discovery", model_id=AppSettings().ai.discovery_model) is None
        assert db.scalar(select(ApplicationAIResult)) is None
        if failure in {"decomposition", "validation", "matching", "criteria storage"}:
            analyses = db.scalars(select(Analysis)).all()
            assert [analysis.id for analysis in analyses] == ([prior_id] if prior_id is not None else [])


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["screen", "score-current"])
async def test_single_pass_storage_failure_retains_known_reply_cost(monkeypatch, kind):
    from app.ai.schemas import ScreeningReport
    from app.db.models import RunLock

    app, db, provider = setup_app(UserRole.MEMBER)
    add_eligible(db, email="synthetic@example.com", raw_hash="synthetic")
    model = AppSettings().ai.screening_model if kind == "screen" else AppSettings().ai.dimension_scoring_model
    if kind == "score-current":
        create_analysis(db, user=db.scalar(select(User)), opening_id=current_opening_id(db),
            report=a_pattern_report(), narrative=None, inputs_fingerprint="prior")
    provider.queue(ScreeningReport(flags=[]) if kind == "screen" else a_scoring_report(),
        model_id=model, input_tokens=1000, output_tokens=200)

    def fail(*_args, **_kwargs):
        raise ValueError("Synthetic storage failure")

    monkeypatch.setattr("app.ai.analysis.store_result" if kind == "screen" else "app.ai.dimension_scoring.stage_result", fail)
    route = "/screening/run" if kind == "screen" else "/ranking/score-current"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        events = await stream_events(client, route)
    ledger = db.scalar(select(RunCostLedger))
    assert ledger.status == "failed"
    assert ledger.failure_type == "ValueError"
    assert sum(row.cost_usd for row in ledger.passes) == pytest.approx(cost_usd(model, Usage(input_tokens=1000, output_tokens=200)))
    assert ledger.passes[0].calls == 1
    assert ledger.passes[0].failed_calls == 1
    assert ledger.passes[0].fresh_units is None
    assert events[-1]["type"] == "error"
    assert not any(event["type"] == "summary" for event in events)
    assert db.get(RunLock, 1, populate_existing=True).holder_user_id is None


@pytest.mark.anyio
@pytest.mark.parametrize("proposed", [False, True])
async def test_seed_failure_preserves_proposals_or_records_degraded_discovery(monkeypatch, proposed):
    from app.db.models import MemberRanking
    from app.services.settings import get_app_settings, save_app_settings
    app, db, provider = setup_app(UserRole.ADMIN)
    add_eligible(db, email="synthetic@example.com", raw_hash="synthetic")
    opening_id = current_opening_id(db)
    settings = get_app_settings(db)
    settings.ai.discovery_fan_out = 2
    save_app_settings(db, settings)
    prior = None
    if proposed:
        prior = create_analysis(db, user=db.scalar(select(User)), opening_id=opening_id,
            report=a_pattern_report(), narrative=None, inputs_fingerprint="prior")
        member = db.scalar(select(MemberRanking).where(MemberRanking.analysis_id == prior.id))
        member.run_state = {**member.run_state, "proposed_dimensions": ["Conflict mediation"]}
        db.commit()
    route_criteria(provider, a_pattern_report())
    provider.route("applicant_id", a_scoring_report())
    original = provider.structured_output
    def flaky(**kwargs):
        if kwargs["schema"].__name__ == "PoolDimensionReport" and kwargs.get("on_delta") is not None:
            raise TimeoutError("Synthetic seeded worker failure")
        return original(**kwargs)
    monkeypatch.setattr(provider, "structured_output", flaky)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        events = await stream_events(client, "/ranking/run")
    ledger = db.scalar(select(RunCostLedger).order_by(RunCostLedger.id.desc()))
    discovery = next(row for row in ledger.passes if row.label == "Pattern discovery")
    assert discovery.failed_calls == 1
    assert discovery.calls == 1
    if proposed:
        assert ledger.status == "failed"
        assert events[-1]["type"] == "error"
        assert db.scalar(select(Analysis.id).order_by(Analysis.id.desc())) == prior.id
        assert member.run_state["proposed_dimensions"] == ["Conflict mediation"]
    else:
        assert ledger.status == "completed"
        assert events[-1]["type"] == "summary"
