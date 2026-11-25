"""Score-only estimates and execution consume one captured, reasoning-aware plan."""

import importlib

import pytest
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import select

from app.ai.dimension_scoring import score_dimensions
from app.ai.model_catalog import MODEL_IDS_BY_ROUTE
from app.ai.schemas import DimensionScoringReport
from app.db.models import RunLock, User, UserRole
from app.schemas.settings import AppSettings
from app.services.ranking.analysis import create_analysis
from app.services.ranking.view import candidate_scores, selected_application_scores
from app.services.settings import save_app_settings
from tests.application_support import current_opening_id
from tests.ranking_support import (
    a_pattern_report,
    a_pattern_report_v2,
    a_scoring_report,
    add_eligible,
    setup_app,
    stream_events,
)


@pytest.mark.anyio
@pytest.mark.parametrize("new_applicant", [False, True])
async def test_score_only_restores_cached_choices_for_the_entire_pool(new_applicant) -> None:
    app, db, provider = setup_app(UserRole.MEMBER)
    applicant = add_eligible(db, email="synthetic@example.com", raw_hash="synthetic")
    report, settings = a_pattern_report(), AppSettings()
    analysis = create_analysis(db, user=db.scalar(select(User)), opening_id=current_opening_id(db),
        report=report, narrative=None, inputs_fingerprint="synthetic")
    original_model = settings.ai.dimension_scoring_model
    for model, value in [(original_model, 0.8), (MODEL_IDS_BY_ROUTE["bedrock"]["sonnet"], -0.6)]:
        settings.ai.dimension_scoring_model = model
        output = a_scoring_report()
        for score in output.scores:
            score.score = value
        provider.queue(output, model_id=model)
        list(score_dimensions(db, provider, applications=[applicant], report=report, settings=settings, max_workers=1))
    settings.ai.dimension_scoring_model = original_model
    save_app_settings(db, settings)
    if new_applicant:
        add_eligible(db, email="new@example.com", raw_hash="new")
        provider.queue(a_scoring_report(), model_id=original_model)
    calls_before = len(provider.calls)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        estimate = (await client.get("/ranking/score-current/estimate")).json()
        assert estimate["toAnalyze"] == int(new_applicant)
        if not new_applicant:
            assert estimate["estimatedUsd"] == 0
        summary = (await stream_events(client, f"/ranking/score-current?analysis_id={estimate['analysisId']}"))[-1]
        assert summary["scored"] == int(new_applicant)
        assert (await client.get("/dashboard")).json()["workflow"]["rankingCurrent"] is True
        assert (await client.get("/ranking/score-current/estimate")).json()["toAnalyze"] == 0
        assert (await client.post(f"/ranking/score-current?analysis_id={estimate['analysisId']}")).status_code == 409
    assert len(provider.calls) == calls_before + int(new_applicant)
    assert [score.score for score in candidate_scores(db, analysis)[0].scores] == [0.8, 0.8]
    assert {row.model_id for row in selected_application_scores(db, applicant.id, report)} == {original_model}
    assert db.get(RunLock, 1).holder_user_id is None


@pytest.mark.anyio
async def test_score_only_refuses_criteria_changed_while_claiming_the_lease(monkeypatch) -> None:
    app, db, provider = setup_app(UserRole.MEMBER)
    add_eligible(db, email="synthetic@example.com", raw_hash="synthetic")
    user, opening_id = db.scalar(select(User)), current_opening_id(db)
    confirmed = create_analysis(db, user=user, opening_id=opening_id, report=a_pattern_report(), narrative=None, inputs_fingerprint="first")
    module = importlib.import_module("app.api.ranking.score_current")
    acquire = module.acquire_run_lock
    report = a_pattern_report_v2()
    later = []

    def finish_previous_run_then_claim(_db, **kwargs):
        later.append(create_analysis(db, user=user, opening_id=opening_id, report=report, narrative=None, inputs_fingerprint="later"))
        return acquire(_db, **kwargs)

    monkeypatch.setattr(module, "acquire_run_lock", finish_previous_run_then_claim)
    base_score = a_scoring_report().scores[0]
    provider.queue(DimensionScoringReport(scores=[base_score.model_copy(update={"dimension_key": dim.key}) for dim in report.dimensions]))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post(f"/ranking/score-current?analysis_id={confirmed.id}")
    assert response.status_code == 409
    assert response.json()["code"] == "stale_analysis"
    assert provider.calls == []
    assert candidate_scores(db, later[0]) == []
    assert db.get(RunLock, 1, populate_existing=True).holder_user_id is None


@pytest.mark.anyio
async def test_estimate_waits_for_in_place_consolidation_and_confirmation_is_required():
    from app.services.run_lock import acquire_run_lock, release_run_lock

    app, db, provider = setup_app(UserRole.MEMBER)
    add_eligible(db, email="fictional@example.com", raw_hash="fictional")
    user = db.scalar(select(User))
    analysis = create_analysis(db, user=user, opening_id=current_opening_id(db), report=a_pattern_report(),
        narrative=None, inputs_fingerprint="fictional")
    lease = acquire_run_lock(db, user_id=user.id, kind="rank")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        busy = await client.get("/ranking/score-current/estimate")
        assert busy.status_code == 409
        assert busy.json()["code"] == "run_in_progress"
        db.rollback()
        analysis.dimension_report = a_pattern_report_v2().model_dump(mode="json")
        db.commit()
        release_run_lock(db, lease)
        estimate = (await client.get("/ranking/score-current/estimate")).json()
        assert estimate["analysisId"] == analysis.id
        assert (await client.post("/ranking/score-current")).status_code == 422
    assert provider.calls == []


@pytest.mark.anyio
async def test_reasoning_cache_coverage_matches_execution() -> None:
    app, db, provider = setup_app(UserRole.MEMBER)
    applicant = add_eligible(db, email="synthetic@example.com", raw_hash="synthetic")
    report, settings = a_pattern_report(), AppSettings()
    settings.ai.dimension_scoring_model = MODEL_IDS_BY_ROUTE["bedrock"]["luna"]
    settings.ai.dimension_scoring_reasoning_effort = "high"
    save_app_settings(db, settings)
    create_analysis(db, user=db.scalar(select(User)), opening_id=current_opening_id(db), report=report, narrative=None, inputs_fingerprint="synthetic")
    provider.queue(a_scoring_report(), model_id=settings.ai.dimension_scoring_model)
    list(score_dimensions(db, provider, applications=[applicant], report=report, settings=settings, max_workers=1))
    add_eligible(db, email="new@example.com", raw_hash="new")
    provider.queue(a_scoring_report(), model_id=settings.ai.dimension_scoring_model)
    calls_before = len(provider.calls)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        estimate = (await client.get("/ranking/score-current/estimate")).json()
        assert estimate["toAnalyze"] == 1
        assert estimate["cached"] == 1
        summary = (await stream_events(client, f"/ranking/score-current?analysis_id={estimate['analysisId']}"))[-1]
        assert summary["scored"] == 1
    assert len(provider.calls) == calls_before + 1
    rows = selected_application_scores(db, applicant.id, report)
    assert {row.reasoning_effort for row in rows} == {"high"}
