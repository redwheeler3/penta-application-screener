from datetime import UTC, datetime, timedelta

import pytest
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.db.models import DailyMaintenanceRun
from app.main import create_app
from app.services import maintenance
from app.services.email.sender import CapturedEmailSender
from app.services.maintenance import run_due_maintenance_with
from tests.db_support import memory_engine, memory_session


def _db():
    return memory_session()


def test_maintenance_claims_once_per_pacific_day() -> None:
    db = _db()
    sender = CapturedEmailSender()
    now = datetime(2026, 8, 26, 18, tzinfo=UTC)

    assert run_due_maintenance_with(db, sender, now=now) is True
    assert run_due_maintenance_with(db, sender, now=now + timedelta(hours=1)) is False
    assert run_due_maintenance_with(db, sender, now=now + timedelta(days=1)) is True

    runs = db.scalars(select(DailyMaintenanceRun).order_by(DailyMaintenanceRun.id)).all()
    assert len(runs) == 2
    assert all(run.status == "completed" for run in runs)


def test_expired_maintenance_recovers_with_sqlite_timestamps() -> None:
    factory = sessionmaker(bind=memory_engine(), autoflush=False)
    now = datetime(2026, 8, 26, 18, tzinfo=UTC)
    with factory() as db:
        assert maintenance._claim_daily_run(db, now=now) is not None
    with factory() as db:
        assert run_due_maintenance_with(db, CapturedEmailSender(), now=now + timedelta(minutes=11))
        run = db.scalar(select(DailyMaintenanceRun))
        assert run.status == "completed"
        assert run.attempt_count == 2


@pytest.mark.parametrize("fails", [False, True])
def test_obsolete_maintenance_cannot_finish_its_replacement(monkeypatch, fails) -> None:
    factory = sessionmaker(bind=memory_engine(), autoflush=False)
    now = datetime(2026, 8, 26, 18, tzinfo=UTC)

    def replace_worker(_db, **_kwargs):
        with factory() as replacement:
            assert maintenance._claim_daily_run(replacement, now=now + timedelta(minutes=11)) is not None
        if fails:
            raise ValueError("Synthetic obsolete failure")

    monkeypatch.setattr(maintenance, "queue_due_unsuccessful_notices", replace_worker)
    monkeypatch.setattr(maintenance, "retry_queued_emails", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(maintenance, "purge_due_applicant_data", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(maintenance, "purge_expired_vacancy_delivery_failures", lambda *_args, **_kwargs: None)
    with factory() as db:
        assert not run_due_maintenance_with(db, CapturedEmailSender(), now=now)
    with factory() as db:
        run = db.scalar(select(DailyMaintenanceRun))
        assert run.status == "running"
        assert run.attempt_count == 2
        assert run.last_error_code is None


@pytest.mark.anyio
async def test_real_request_triggers_maintenance_but_inert_requests_do_not() -> None:
    calls = 0

    def maintenance_task() -> None:
        nonlocal calls
        calls += 1

    app = create_app(maintenance_task=maintenance_task)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await client.get("/health")
        await client.get("/assets/missing.css")
        await client.get("/dev/previews/emails")
        await client.get("/dashboard")

    assert calls == 1
