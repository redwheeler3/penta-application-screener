"""Every paid run uses the same fence and reports a superseded acquisition as a fatal event."""

import importlib
from datetime import UTC, datetime, timedelta

import pytest
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.ai.schemas import ScreeningReport
from app.db.models import (
    Analysis,
    ApplicationAIResult,
    Opening,
    RunLock,
    User,
    UserRole,
)
from app.services.ranking.analysis import create_analysis
from app.services.run_lock import LEASE_TTL, acquire_run_lock
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
@pytest.mark.parametrize("kind", ["rank", "screen", "score-current"])
async def test_preflight_rechecks_finality_after_lease_acquisition(monkeypatch, kind):
    app, db, provider = setup_app(UserRole.MEMBER)
    add_eligible(db, email="synthetic@example.com", raw_hash="synthetic")
    opening_id = current_opening_id(db)
    module = importlib.import_module({"rank": "app.api.ranking.run", "screen": "app.api.screening",
        "score-current": "app.api.ranking.score_current"}[kind])
    original = module.acquire_run_lock

    def finalize_then_claim(session, **kwargs):
        with Session(db.bind) as other:
            other.execute(update(Opening).where(Opening.id == opening_id).values(decided_at=datetime.now(UTC)))
            other.commit()
        return original(session, **kwargs)

    monkeypatch.setattr(module, "acquire_run_lock", finalize_then_claim)
    route = {"rank": "/ranking/run", "screen": "/screening/run", "score-current": "/ranking/score-current?analysis_id=1"}[kind]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post(route)
    assert response.status_code == 409
    assert response.json()["code"] == "opening_finalized"
    assert provider.calls == []
    assert db.get(RunLock, 1, populate_existing=True).holder_user_id is None


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["rank", "screen", "score-current"])
async def test_superseded_runs_report_failure_and_cannot_persist_results(monkeypatch, kind) -> None:
    app, db, provider = setup_app(UserRole.MEMBER)
    add_eligible(db, email="synthetic@example.com", raw_hash="synthetic")
    other_user = User(email="other@example.com", display_name="Other", role=UserRole.MEMBER)
    db.add(other_user)
    db.commit()
    other_user_id = other_user.id
    if kind == "rank":
        module = importlib.import_module("app.services.ranking.pipeline")
        function = "create_analysis"
        route = "/ranking/run"
        route_criteria(provider, a_pattern_report())
    elif kind == "screen":
        module = importlib.import_module("app.ai.analysis")
        function = "store_result"
        route = "/screening/run"
        provider.queue(ScreeningReport(flags=[]))
    else:
        module = importlib.import_module("app.ai.dimension_scoring")
        function = "stage_result"
        analysis = create_analysis(db, user=db.scalar(select(User).where(User.id != other_user_id)),
            opening_id=current_opening_id(db), report=a_pattern_report(), narrative=None, inputs_fingerprint="original")
        route = f"/ranking/score-current?analysis_id={analysis.id}"
        provider.queue(a_scoring_report())
    original = getattr(module, function)
    replacement = []

    def supersede_before_write(*args, **kwargs):
        if not replacement:
            with Session(db.bind) as other:
                now = datetime.now(UTC)
                other.execute(update(RunLock).values(renewed_at=now - LEASE_TTL - timedelta(seconds=1)))
                other.commit()
                replacement.append(acquire_run_lock(other, user_id=other_user_id, kind="rank", now=now))
        return original(*args, **kwargs)

    monkeypatch.setattr(module, function, supersede_before_write)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        events = await stream_events(client, route)
    assert replacement[0] is not None
    assert events[-1]["type"] == "error"
    assert not any(event["type"] == "summary" for event in events)
    assert db.scalar(select(ApplicationAIResult)) is None
    assert len(db.scalars(select(Analysis)).all()) == (1 if kind == "score-current" else 0)
    assert db.get(RunLock, 1, populate_existing=True).holder_user_id == other_user_id


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["screen", "rank", "score-current"])
@pytest.mark.parametrize("change", ["withdraw", "decide", "dispatch-first"])
async def test_paid_dispatch_is_ordered_against_pool_and_final_decision(kind, change):
    import json

    from app.api.ranking.run import rank_run
    from app.api.ranking.score_current import score_current
    from app.api.screening import run as screen
    from app.core.problems import Problem
    from app.core.time import pacific_today
    from app.db.models import Application
    from app.services.openings.selection import confirm_no_household_selected

    _, db, provider = setup_app(UserRole.ADMIN)
    applicant = add_eligible(db, email="fixture@example.com", raw_hash="fixture")
    aid, oid = applicant.id, current_opening_id(db)
    db.get(Opening, oid).application_close_date = pacific_today() - timedelta(days=1)
    db.commit()
    user = db.scalar(select(User))
    uid = user.id
    kwargs = {"opening_id": oid, "user": user, "db": db, "provider": provider}
    if kind == "screen":
        provider.queue(ScreeningReport(flags=[]))
        response = screen(**kwargs)
    elif kind == "rank":
        route_criteria(provider, a_pattern_report())
        provider.route("applicant_id", a_scoring_report())
        response = rank_run(**kwargs)
    else:
        prior = create_analysis(db, user=user, opening_id=oid, report=a_pattern_report(), narrative=None, inputs_fingerprint="fixture")
        provider.queue(a_scoring_report())
        response = score_current(analysis_id=prior.id, **kwargs)

    iterator = response.body_iterator
    if change == "dispatch-first":
        assert json.loads(await anext(iterator))["type"] == "phase"
    with Session(db.bind) as other:
        if change == "withdraw":
            other.get(Application, aid).withdrawn_at = datetime.now(UTC)
            other.commit()
        elif change == "decide":
            confirm_no_household_selected(other, other.get(Opening, oid), decided_by=other.get(User, uid))
        else:
            with pytest.raises(Problem, match="AI work is running"):
                confirm_no_household_selected(other, other.get(Opening, oid), decided_by=other.get(User, uid))
            other.rollback()
    events = [json.loads(line) async for line in iterator]
    if change == "dispatch-first":
        assert events[-1]["type"] == "summary"
        assert provider.calls
        confirm_no_household_selected(db, db.get(Opening, oid), decided_by=user)
    else:
        assert events[-1]["type"] == "error"
        assert provider.calls == []
        assert len(db.scalars(select(Analysis)).all()) == int(kind == "score-current")
    assert db.get(RunLock, 1, populate_existing=True).holder_user_id is None
