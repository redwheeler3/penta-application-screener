"""A run's freshness describes its starting inputs, including edits made during AI work."""

import json
from threading import Event

import pytest
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import select

from app.ai.analysis import AnalysisOutcome, PassResult
from app.ai.pricing import PassCost
from app.ai.schemas import DimensionScoringReport
from app.db.models import User, UserRole
from app.schemas.settings import AppSettings
from app.services.ranking.analysis import create_analysis, ranking_is_current
from app.services.ranking.criteria import CriteriaPassResult, CriteriaStageChange
from app.services.ranking.freshness import rank_inputs_fingerprint
from app.services.ranking.pipeline import _stream_criteria
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
    assert ranking_is_current(db, result.analysis, settings) is False


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
        response = await client.post(f"/ranking/score-current?opening_id={opening_id}")
    assert response.status_code == 200
    assert seen_hashes == ["ready-for-scoring"]
    assert analysis.rank_inputs_fingerprint == scoring_fingerprint
    assert ranking_is_current(db, analysis, settings) is False
