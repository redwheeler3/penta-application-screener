"""A board captures one analysis, and overlapping first reads share one member view."""

import pytest
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import event, select
from sqlalchemy.orm import sessionmaker

from app.ai.dimension_scoring import score_dimensions
from app.api.ranking import shortlist
from app.db.models import Analysis, ApplicationAIResult, User, UserRole
from app.schemas.ranking import ProposalUpdate, TierLayoutUpdate
from app.schemas.settings import AppSettings
from app.services.cached_results import refresh_cached_results
from app.services.ranking.analysis import create_analysis
from app.services.ranking.member_state import get_or_reconcile_member_ranking
from app.services.ranking.provenance import rank_inputs_fingerprint
from tests.application_support import current_opening_id
from tests.db_support import add_selected_result
from tests.ranking_support import (
    a_pattern_report,
    a_pattern_report_v2,
    a_scoring_report,
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
async def test_completed_shared_scoring_changes_the_board_without_analysis_or_adoption_change():
    app, db, provider = setup_app(UserRole.MEMBER)
    first = add_eligible(db, email="first@example.com", raw_hash="first")
    report, settings = a_pattern_report(), AppSettings()
    analysis = seed_analysis(db, db.scalar(select(User)), report)
    provider.queue(a_scoring_report())
    list(score_dimensions(db, provider, applications=[first], report=report, settings=settings, max_workers=1))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        before = (await client.get("/ranking/board")).json()
        second = add_eligible(db, email="second@example.com", raw_hash="second")
        provider.queue(a_scoring_report())
        list(score_dimensions(db, provider, applications=[second], report=report, settings=settings, max_workers=1))
        assert not refresh_cached_results(db, current_opening_id(db))
        after = (await client.get("/ranking/board")).json()
    assert before["ranking"]["scoredCount"] == 1
    assert after["ranking"]["scoredCount"] == 2
    assert before["run"]["analysisId"] == after["run"]["analysisId"] == analysis.id


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


def test_tier_save_acknowledges_its_layout_when_another_tab_saves_after_commit(monkeypatch):
    _app, db, _provider = setup_app(UserRole.MEMBER)
    first = add_eligible(db, email="first@example.com", raw_hash="first")
    second = add_eligible(db, email="second@example.com", raw_hash="second")
    user = db.scalar(select(User))
    user_id, opening_id = user.id, current_opening_id(db)
    analysis_id = seed_analysis(db, user, a_pattern_report()).id
    for application, participation, skills in [(first, -0.8, 0.9), (second, 0.9, -0.8)]:
        for key, score in [("participation_commitment", participation), ("skills_offered", skills)]:
            add_selected_result(db, ApplicationAIResult(producer_application_id=application.id,
                kind=f"dimension_scoring:{key}", cache_key=f"synthetic-{application.id}-{key}",
                model_id="synthetic", prompt_version="synthetic", output={"score": score}))
    db.commit()
    factory = sessionmaker(bind=db.get_bind(), autoflush=False)
    layout_a = TierLayoutUpdate(analysisId=analysis_id,
        tiers=[{"id": "a", "label": "Skills", "dimensionKeys": ["skills_offered"]}])
    layout_b = TierLayoutUpdate(analysisId=analysis_id,
        tiers=[{"id": "b", "label": "Participation", "dimensionKeys": ["participation_commitment"]}])
    with factory() as tab_a:
        commit = tab_a.commit
        other_receipts = []

        def commit_then_save_in_other_tab():
            commit()
            with factory() as tab_b:
                member = tab_b.get(User, user_id)
                shortlist.update_proposal(ProposalUpdate(analysisId=analysis_id, operation="add",
                    text="Synthetic next-run proposal"), opening_id, member, tab_b)
                other_receipts.append(shortlist.update_tiers(layout_b, opening_id, member, tab_b))

        monkeypatch.setattr(tab_a, "commit", commit_then_save_in_other_tab)
        acknowledged = shortlist.update_tiers(layout_a, opening_id, tab_a.get(User, user_id), tab_a)
    assert len(other_receipts) == 1
    assert acknowledged.weights == {"participation_commitment": 0.0, "skills_offered": 1.0}
    assert [candidate.application_id for candidate in acknowledged.candidates] == [first.id, second.id]
    assert other_receipts[0].weights == {"participation_commitment": 1.0, "skills_offered": 0.0}
    with factory() as reader:
        board = shortlist.ranking_board(opening_id, reader.get(User, user_id), reader)
    assert board.ranking.weights == other_receipts[0].weights
    assert [candidate.application_id for candidate in board.ranking.candidates] == [second.id, first.id]
    assert board.tiers[0].label == "Participation"
    assert board.run.proposed_dimensions == ["Synthetic next-run proposal"]
