"""A run's provenance records its starting inputs, including edits made during AI work."""

import json
from datetime import UTC, datetime
from threading import Event

import pytest
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import select

from app.ai.analysis import AnalysisOutcome, PassResult
from app.ai.pricing import PassCost
from app.ai.schemas import DimensionScoringReport
from app.db.models import User, UserRole
from app.schemas.settings import AppSettings
from app.services.ranking.analysis import create_analysis
from app.services.ranking.criteria import CriteriaPassResult, CriteriaStageChange
from app.services.ranking.pipeline import _stream_criteria
from app.services.ranking.provenance import rank_inputs_fingerprint
from tests.application_support import current_opening_id
from tests.ranking_support import a_pattern_report, add_eligible, setup_app


@pytest.mark.parametrize("change", ["edit", "join"])
def test_discovery_keeps_its_starting_fingerprint_when_the_pool_changes(monkeypatch, change) -> None:
    _app, db, provider = setup_app(UserRole.MEMBER)
    application = add_eligible(db, email="synthetic@example.com", raw_hash="original-input")
    user = db.scalar(select(User))
    opening_id = current_opening_id(db)
    settings = AppSettings()
    original_fingerprint = rank_inputs_fingerprint(db, opening_id, settings)
    allow_completion = Event()
    seen_hashes = []

    def delayed_criteria(*_args, **kwargs):
        seen_hashes.extend(app.raw_row_hash for app in kwargs["applications"])
        kwargs["on_delta"](CriteriaStageChange("discovering"))
        assert allow_completion.wait(5), "Request did not release the synthetic worker"
        return CriteriaPassResult(
            report=a_pattern_report(), narrative=None, new_to_old={},
            discovery_cost=PassCost(), decompose_cost=PassCost(), match_cost=PassCost(),
            durations={}, fan_out_audit={"k": 1, "failed_count": 0, "passes": []},
            decompose_audit={}, match_audit={},
        )

    monkeypatch.setattr("app.services.ranking.pipeline.run_criteria_passes", delayed_criteria)
    stream = _stream_criteria(db, provider, settings, user, opening_id, estimated_usd=0.2)
    try:
        while True:
            try:
                event = json.loads(next(stream))
            except StopIteration as finished:
                result = finished.value
                break
            if event["type"] == "stage":
                if change == "edit":
                    application.raw_row_hash = "edited-during-discovery"
                    db.commit()
                else:
                    add_eligible(db, email="new@example.com", raw_hash="new-during-discovery")
                allow_completion.set()
    finally:
        allow_completion.set()
    assert seen_hashes == ["original-input"]
    assert result.analysis.rank_inputs_fingerprint == original_fingerprint
    assert result.analysis.rank_inputs_fingerprint != rank_inputs_fingerprint(db, opening_id, settings)


@pytest.mark.anyio
async def test_score_current_keeps_its_starting_fingerprint_after_an_edit(monkeypatch) -> None:
    app, db, _provider = setup_app(UserRole.MEMBER)
    application = add_eligible(db, email="synthetic@example.com", raw_hash="initial-input")
    opening_id = current_opening_id(db)
    settings = AppSettings()
    analysis = create_analysis(
        db, user=db.scalar(select(User)), opening_id=opening_id, report=a_pattern_report(),
        inputs_fingerprint=rank_inputs_fingerprint(db, opening_id, settings), narrative=None,
    )
    application.raw_row_hash = "ready-for-scoring"
    db.commit()
    scoring_fingerprint = rank_inputs_fingerprint(db, opening_id, settings)
    seen_hashes = []

    def delayed_scores(_db, _provider, *, plan, **_kwargs):
        applications = [app.application for app in plan.applicants]
        seen_hashes.extend(candidate.raw_row_hash for candidate in applications)
        yield PassResult(
            application=applications[0],
            outcome=AnalysisOutcome(output=DimensionScoringReport(scores=[]), cost_usd=0, cached=False),
        )
        application.raw_row_hash = "edited-during-scoring"
        db.commit()

    monkeypatch.setattr("app.api.ranking.score_current.score_planned_dimensions", delayed_scores)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post(f"/ranking/score-current?opening_id={opening_id}&analysis_id={analysis.id}")
    assert response.status_code == 200
    assert seen_hashes == ["ready-for-scoring"]
    assert analysis.rank_inputs_fingerprint == scoring_fingerprint
    assert analysis.rank_inputs_fingerprint != rank_inputs_fingerprint(db, opening_id, settings)


@pytest.mark.anyio
@pytest.mark.parametrize("source_present", [False, True])
async def test_rank_cleans_expired_history_or_refuses_missing_sources_before_provider_work(source_present):
    from app.ai.schemas import DimensionMatchReport
    from app.core.time import pacific_today
    from app.db.models import Analysis, AnalysisAudit, Application, RunLock
    from tests.ranking_support import a_scoring_report, route_criteria

    app, db, provider = setup_app(UserRole.ADMIN)
    add_eligible(db, email="retained@example.com", raw_hash="retained")
    marker = "Expired synthetic explanation marker"
    if source_present:
        expired = Application(primary_email="expired@example.com", raw_row={}, raw_row_hash="expired", normalized={},
            submitted_at=datetime.now(UTC), retention_due_on=pacific_today())
        db.add(expired)
        db.flush()
        source_id = expired.id
    else:
        source_id = 123456
    report = a_pattern_report()
    report.dimensions[0].why_it_differentiates = marker
    history = Analysis(dimension_report=report.model_dump(mode="json"), source_application_ids=[source_id],
        audit=AnalysisAudit(discovery_narrative=marker))
    db.add(history)
    db.commit()
    route_criteria(provider, a_pattern_report())
    provider.route("<prior_dimensions>", DimensionMatchReport(matches=[]))
    provider.route("applicant_id", a_scoring_report())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post("/ranking/run")
    if source_present:
        assert response.status_code == 200
        assert json.loads(response.text.splitlines()[-1])["type"] == "summary"
        assert provider.calls
        assert all(marker not in call.prompt for call in provider.calls)
        assert db.get(Application, source_id) is None
        assert history.audit is None
        assert history.pool_text_purged
    else:
        assert response.status_code == 409
        assert response.json()["code"] == "rank_inputs_unavailable"
        assert provider.calls == []
    assert db.get(RunLock, 1, populate_existing=True).holder_user_id is None


@pytest.mark.anyio
async def test_rank_still_fences_source_expiry_during_paid_work(monkeypatch):
    from app.core.time import pacific_today
    from app.db.models import Analysis, RunLock
    from app.services.ranking import pipeline
    from tests.ranking_support import route_criteria, stream_events

    app, db, provider = setup_app(UserRole.ADMIN)
    application = add_eligible(db, email="fictional@example.com", raw_hash="fictional")
    original = pipeline.create_analysis
    def expire_then_publish(*args, **kwargs):
        application.retention_due_on = pacific_today()
        db.commit()
        return original(*args, **kwargs)
    monkeypatch.setattr(pipeline, "create_analysis", expire_then_publish)
    route_criteria(provider, a_pattern_report())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        events = await stream_events(client, "/ranking/run")
    assert provider.calls
    assert events[-1]["type"] == "error"
    assert db.scalar(select(Analysis)) is None
    assert db.get(RunLock, 1, populate_existing=True).holder_user_id is None


@pytest.mark.parametrize(("field", "value"), [("discovery_fan_out", 6),
                                        ("consolidate_correlation_threshold", 0.4)])
def test_semantic_strategy_controls_are_part_of_captured_inputs(field, value):
    _, db, _ = setup_app(UserRole.MEMBER)
    add_eligible(db, email="strategy@example.test", raw_hash="same")
    user = db.scalar(select(User))
    opening_id = current_opening_id(db)
    settings = AppSettings()
    from app.services.ranking.provenance import rank_configuration
    captured = rank_configuration(settings)
    analysis = create_analysis(db, user=user, opening_id=opening_id, report=a_pattern_report(),
                               inputs_fingerprint=rank_inputs_fingerprint(db, opening_id, settings),
                               narrative=None, fan_out_audit={"k": 5, "passes": []}, configuration=captured)
    assert analysis.rank_inputs_fingerprint == rank_inputs_fingerprint(db, opening_id, settings)
    settings.ai.max_workers += 1
    assert analysis.rank_inputs_fingerprint == rank_inputs_fingerprint(db, opening_id, settings)  # scheduling is not evidence
    setattr(settings.ai, field, value)
    assert analysis.rank_inputs_fingerprint != rank_inputs_fingerprint(db, opening_id, settings)
    assert analysis.audit.fan_out["configuration"] == captured
    assert captured["strategy"][field] != value
