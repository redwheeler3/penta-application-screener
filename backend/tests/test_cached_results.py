"""Background cache reuse is bounded bookkeeping, never an AI run."""

import importlib
from datetime import UTC, datetime, timedelta

import pytest
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.ai.analysis import cache_key
from app.ai.dimension_scoring import (
    kind_for_dimension,
    score_dimensions,
)
from app.ai.model_catalog import MODEL_IDS_BY_ROUTE
from app.ai.schemas import ScreeningReport
from app.ai.screening import run_screening, screening_prompt_version
from app.db.models import (
    Application,
    ApplicationAIResult,
    ApplicationAISelection,
    RunCostLedger,
    User,
    UserRole,
)
from app.schemas.settings import AppSettings
from app.services.cached_results import refresh_cached_results
from app.services.ranking.analysis import create_analysis, ranking_is_current
from app.services.ranking.freshness import rank_configuration, rank_inputs_fingerprint
from app.services.ranking.view import candidate_scores
from app.services.run_lock import acquire_run_lock
from tests.ranking_support import (
    a_pattern_report,
    a_scoring_report,
    add_eligible,
    setup_app,
)


def cached_pool():
    app, db, provider = setup_app(UserRole.MEMBER)
    producer = add_eligible(db, email="producer@example.com", raw_hash="same")
    settings, report = AppSettings(), a_pattern_report()
    from tests.application_support import current_opening_id
    opening_id = current_opening_id(db)
    analysis = create_analysis(db, user=db.scalar(select(User)), opening_id=opening_id,
        report=report, narrative=None, inputs_fingerprint=rank_inputs_fingerprint(db, opening_id, settings),
        configuration=rank_configuration(settings))
    provider.queue(ScreeningReport(flags=[]))
    list(run_screening(db, provider, applications=[producer], settings=settings, max_workers=1))
    provider.queue(a_scoring_report())
    list(score_dimensions(db, provider, applications=[producer], report=report, settings=settings, max_workers=1))
    consumer = add_eligible(db, email="consumer@example.com", raw_hash="same")
    return app, db, provider, producer, consumer, analysis, settings, opening_id


@pytest.mark.anyio
async def test_background_reuses_screening_and_scores_without_provider_calls_or_run_costs():
    app, db, provider, producer, consumer, analysis, settings, opening_id = cached_pool()
    calls = len(provider.calls)
    costs = db.scalar(select(func.count()).select_from(RunCostLedger))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post(f"/cached-results/refresh?opening_id={opening_id}")
        assert response.status_code == 200
        assert response.json() == {"changed": True}
        assert (await client.post(f"/cached-results/refresh?opening_id={opening_id}")).json() == {"changed": False}
        assert (await client.get("/screening/run/estimate")).json()["toAnalyze"] == 0
        assert (await client.get("/ranking/score-current/estimate")).json()["toAnalyze"] == 0
    for kind in ["screening", *(kind_for_dimension(dim.key) for dim in a_pattern_report().dimensions)]:
        assert db.get(ApplicationAISelection, (producer.id, kind)).result_id == db.get(ApplicationAISelection, (consumer.id, kind)).result_id
    assert len(candidate_scores(db, analysis)) == 2
    assert ranking_is_current(db, analysis, settings)
    assert len(provider.calls) == calls
    assert db.scalar(select(func.count()).select_from(RunCostLedger)) == costs


@pytest.mark.parametrize("change", ["input", "withdraw", "expire", "run"])
def test_background_rechecks_scope_under_writer_before_adopting(change, monkeypatch):
    _app, db, _provider, _producer, consumer, _analysis, _settings, opening_id = cached_pool()
    module = importlib.import_module("app.services.cached_results")
    lock = module.lock_run_state
    def change_then_lock(active_db):
        with Session(db.bind) as other:
            applicant = other.get(Application, consumer.id)
            if change == "input":
                applicant.raw_row_hash = "new evidence"
            elif change == "withdraw":
                applicant.withdrawn_at = datetime.now(UTC)
            elif change == "expire":
                applicant.retention_due_on = datetime.now(UTC).date() - timedelta(days=1)
            else:
                acquire_run_lock(other, user_id=db.scalar(select(User.id)), kind="rank")
            other.commit()
        lock(active_db)
    monkeypatch.setattr(module, "lock_run_state", change_then_lock)
    assert not refresh_cached_results(db, opening_id)
    assert db.get(ApplicationAISelection, (consumer.id, "screening")) is None


@pytest.mark.parametrize("unknown_configuration", [False, True])
def test_score_reuse_does_not_certify_changed_or_unknown_discovery_inputs(unknown_configuration):
    _app, db, _provider, _producer, consumer, analysis, settings, opening_id = cached_pool()
    if unknown_configuration:
        analysis.audit.fan_out = None
    else:
        # A changed strategy needs explicit discovery even when every score is cached.
        settings.ai.discovery_fan_out += 1
        from app.services.settings import save_app_settings
        save_app_settings(db, settings)
    analysis.rank_inputs_fingerprint = "out-of-date"
    db.commit()
    assert refresh_cached_results(db, opening_id)
    assert db.get(ApplicationAISelection, (consumer.id, "screening")) is not None
    assert not ranking_is_current(db, analysis, settings)


def test_genuine_cache_miss_preserves_last_consumed_findings():
    _app, db, _provider, producer, _consumer, _analysis, settings, opening_id = cached_pool()
    earlier = db.get(ApplicationAISelection, (producer.id, "screening")).result_id
    earlier_key = cache_key(application=producer, kind="screening", model_id=settings.ai.screening_model,
        prompt_version=screening_prompt_version())
    producer.raw_row_hash = "resubmitted"
    db.commit()
    refresh_cached_results(db, opening_id)
    assert db.get(ApplicationAISelection, (producer.id, "screening")).result_id == earlier
    assert cache_key(application=producer, kind="screening", model_id=settings.ai.screening_model,
        prompt_version=screening_prompt_version()) != earlier_key


@pytest.mark.parametrize("pass_kind", ["screening", "scoring"])
def test_background_never_adopts_results_for_a_different_model(pass_kind):
    _app, db, provider, _producer, consumer, _analysis, settings, opening_id = cached_pool()
    from app.services.settings import save_app_settings
    if pass_kind == "screening":
        settings.ai.screening_model = MODEL_IDS_BY_ROUTE["bedrock"]["sonnet"]
        kind = "screening"
    else:
        settings.ai.dimension_scoring_model = MODEL_IDS_BY_ROUTE["bedrock"]["sonnet"]
        kind = kind_for_dimension(a_pattern_report().dimensions[0].key)
    save_app_settings(db, settings)
    calls = len(provider.calls)
    refresh_cached_results(db, opening_id)
    assert db.get(ApplicationAISelection, (consumer.id, kind)) is None
    assert len(provider.calls) == calls


def test_partial_cached_scores_stay_partial_and_do_not_certify_rank_freshness():
    _app, db, provider, producer, consumer, analysis, settings, opening_id = cached_pool()
    kind = kind_for_dimension(a_pattern_report().dimensions[0].key)
    result_id = db.get(ApplicationAISelection, (producer.id, kind)).result_id
    db.execute(delete(ApplicationAISelection).where(ApplicationAISelection.result_id == result_id))
    db.execute(delete(ApplicationAIResult).where(ApplicationAIResult.id == result_id))
    db.commit()
    calls = len(provider.calls)
    assert refresh_cached_results(db, opening_id)
    assert db.get(ApplicationAISelection, (consumer.id, kind)) is None
    assert not ranking_is_current(db, analysis, settings)
    assert len(provider.calls) == calls
