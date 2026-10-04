"""Every paid run uses the same fence and reports a superseded acquisition as a fatal event."""

import importlib
from datetime import UTC, datetime, timedelta

import pytest
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.ai.schemas import ScreeningReport
from app.db.models import Analysis, ApplicationAIResult, RunLock, User, UserRole
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
        function = "store_result"
        route = "/ranking/score-current"
        create_analysis(db, user=db.scalar(select(User).where(User.id != other_user_id)),
            opening_id=current_opening_id(db), report=a_pattern_report(), narrative=None, inputs_fingerprint="original")
        provider.queue(a_scoring_report())
    original = getattr(module, function)
    replacement = []

    def supersede_before_write(*args, **kwargs):
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
