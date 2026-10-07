"""Rank projections follow known route prices and work while retaining history weighting."""

import pytest
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import select

from app.ai.model_catalog import MODEL_IDS_BY_ROUTE
from app.ai.pricing import PassCost
from app.db.models import User, UserRole
from app.schemas.settings import AppSettings
from app.services.cost_report import (
    RANK_PASS_LABELS,
    recent_pass_fresh_usd,
    record_run_cost,
)
from app.services.ranking.analysis import create_analysis
from app.services.ranking.estimates import build_rank_estimate
from app.services.settings import save_app_settings
from tests.application_support import current_opening_id
from tests.ranking_support import a_pattern_report, add_eligible, setup_app


def configured(route="bedrock", count=1):
    settings = AppSettings()
    model = MODEL_IDS_BY_ROUTE[route]["luna"]
    for field in ("discovery_model", "decompose_model", "match_model", "dimension_scoring_model", "consolidate_model"):
        setattr(settings.ai, field, model)
    settings.ai.discovery_fan_out = count
    return settings


def record_history(db, opening_id, *, model, tokens=500000, calls=1, status="completed"):
    record_run_cost(db, kind="rank", opening_id=opening_id, status=status,
        passes={label: PassCost(model_id=model, calls=calls, input_tokens=tokens, cost_usd=0.1)
                for label in RANK_PASS_LABELS})


@pytest.mark.anyio
async def test_route_and_discovery_count_reprice_history_and_cap_before_provider_calls():
    app, db, provider = setup_app(UserRole.ADMIN)
    application = add_eligible(db, email="estimate@example.test", raw_hash="estimate")
    opening_id = current_opening_id(db)
    settings = configured()
    create_analysis(db, user=db.scalar(select(User)), opening_id=opening_id,
        report=a_pattern_report(), inputs_fingerprint="synthetic", narrative=None)
    record_history(db, opening_id, model=settings.ai.discovery_model)
    initial = build_rank_estimate(db, opening_id, settings, pool=[application])
    assert initial["estimated_usd"] == 0.5
    changed = configured("direct", 10)
    # Discovery becomes $5 (10 replies), each of the other four passes becomes $0.50.
    assert build_rank_estimate(db, opening_id, changed, pool=[application])["estimated_usd"] == 7
    changed.ai.spending_cap_usd = 1
    save_app_settings(db, changed)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        estimate = (await client.get("/ranking/run/estimate")).json()
        assert estimate["estimatedUsd"] == 7
        assert estimate["approximate"] is True
        assert estimate["withinCap"] is False
        response = await client.post("/ranking/run")
        assert response.status_code == 402
    assert not provider.calls


def test_history_weights_usage_and_normalizes_discovery_by_replies_not_result_units():
    _, db, _ = setup_app(UserRole.MEMBER)
    opening_id = current_opening_id(db)
    model = configured().ai.discovery_model
    record_history(db, opening_id, model=model, tokens=2000000, calls=4)
    record_history(db, opening_id, model=model, tokens=1000000, calls=2)
    record_history(db, opening_id, model=model, tokens=9000000, calls=1, status="failed")
    assert recent_pass_fresh_usd(db, opening_id, "Pattern discovery",
        model_id=model, provider_calls=10) == pytest.approx(1)
    assert recent_pass_fresh_usd(db, opening_id, model_id=model) == pytest.approx((0.4 + 2 * 0.2) / 3)
    # A materially different model does not inherit another model's usage pattern.
    assert recent_pass_fresh_usd(db, opening_id, model_id=MODEL_IDS_BY_ROUTE["direct"]["sonnet"]) is None


def test_first_opening_run_estimates_matching_against_global_history():
    from app.db.models import Opening
    from tests.application_support import current_opening

    _, db, _ = setup_app(UserRole.MEMBER)
    settings = AppSettings()
    opening = current_opening(db)
    assert build_rank_estimate(db, opening.id, settings, pool=[])["breakdown"]["match_usd"] == 0
    create_analysis(db, user=db.scalar(select(User)), opening_id=opening.id,
        report=a_pattern_report(), inputs_fingerprint="synthetic", narrative=None)
    second = Opening(unit_size_bedrooms=1, housing_charge_cents=100000,
        application_open_date=opening.application_open_date,
        application_close_date=opening.application_close_date, move_in_date=opening.move_in_date)
    db.add(second)
    db.commit()
    assert build_rank_estimate(db, second.id, settings, pool=[])["breakdown"]["match_usd"] > 0
