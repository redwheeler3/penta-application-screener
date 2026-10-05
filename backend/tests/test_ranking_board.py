"""A board captures one analysis, and overlapping first reads share one member view."""

import pytest
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import event, select
from sqlalchemy.orm import sessionmaker

from app.api.ranking import shortlist
from app.db.models import Analysis, ApplicationAIResult, User, UserRole
from app.schemas.settings import AppSettings
from app.services.ranking.analysis import create_analysis
from app.services.ranking.freshness import rank_inputs_fingerprint
from app.services.ranking.member_state import get_or_reconcile_member_ranking
from tests.application_support import current_opening_id
from tests.db_support import add_selected_result
from tests.ranking_support import (
    a_pattern_report,
    a_pattern_report_v2,
    add_eligible,
    setup_app,
)


def seed_analysis(db, user, report):
    opening_id = current_opening_id(db)
    return create_analysis(
        db, user=user, opening_id=opening_id, report=report, narrative=None,
        inputs_fingerprint=rank_inputs_fingerprint(db, opening_id, AppSettings()),
    )


@pytest.mark.anyio
async def test_board_stays_coherent_if_another_analysis_is_created_during_its_read(monkeypatch) -> None:
    app, db, _provider = setup_app(UserRole.MEMBER)
    add_eligible(db, email="synthetic@example.com", raw_hash="synthetic")
    user = db.scalar(select(User))
    original = seed_analysis(db, user, a_pattern_report())
    original_id = original.id
    present = shortlist.ranking_payload
    created = []

    def advance_analysis(_db, member_ranking, member):
        created.append(seed_analysis(db, user, a_pattern_report_v2()).id)
        return present(_db, member_ranking, member)

    monkeypatch.setattr(shortlist, "ranking_payload", advance_analysis)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get(f"/ranking/board?opening_id={current_opening_id(db)}")
    assert response.status_code == 200
    board = response.json()
    assert created[0] != original_id
    assert board["run"]["analysisId"] == original_id
    assert board["ranking"]["analysisId"] == original_id
    keys = {dimension["key"] for dimension in board["run"]["dimensions"]}
    assert keys == {"participation_commitment", "skills_offered"}
    assert set(board["ranking"]["weights"]) == keys
    assert {key for tier in board["tiers"] for key in tier["dimensionKeys"]} == keys


def test_competing_first_reads_return_the_same_member_ranking() -> None:
    _app, db, _provider = setup_app(UserRole.MEMBER)
    add_eligible(db, email="synthetic@example.com", raw_hash="synthetic")
    user = db.scalar(select(User))
    other = User(email="other@example.com", display_name="Synthetic other", role=UserRole.MEMBER)
    db.add(other)
    db.commit()
    analysis_id = seed_analysis(db, user, a_pattern_report()).id
    other_id = other.id
    factory = sessionmaker(bind=db.get_bind(), autoflush=False)
    with factory() as first, factory() as second:
        winner_ids = []

        @event.listens_for(first, "before_flush", once=True)
        def competing_read(_session, _context, _instances):
            winner = get_or_reconcile_member_ranking(
                second, second.get(Analysis, analysis_id), second.get(User, other_id),
            )
            winner_ids.append(winner.id)

        result = get_or_reconcile_member_ranking(
            first, first.get(Analysis, analysis_id), first.get(User, other_id),
        )
        assert result.id == winner_ids[0]


@pytest.mark.anyio
async def test_board_does_not_rank_cached_ignored_scores_as_missing_selected_scores():
    app, db, _provider = setup_app(UserRole.MEMBER)
    application = add_eligible(db, email="synthetic@example.com", raw_hash="synthetic")
    user = db.scalar(select(User))
    analysis = seed_analysis(db, user, a_pattern_report())
    analysis_id = analysis.id
    add_selected_result(db, ApplicationAIResult(producer_application_id=application.id,
        kind="dimension_scoring:skills_offered", cache_key="synthetic-ignored",
        model_id="synthetic", prompt_version="synthetic", output={"score": 0.8}))
    db.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.put("/ranking/tiers", json={"analysisId": analysis_id,
            "tiers": [{"id": "chosen", "label": "Chosen",
                "dimensionKeys": ["participation_commitment"]}]})
        assert response.status_code == 200
        assert response.json()["candidates"] == []
        board = (await client.get("/ranking/board")).json()
        assert board["ranking"]["scoredCount"] == 0
        assert board["ranking"]["candidates"] == []
