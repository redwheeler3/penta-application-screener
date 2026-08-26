from datetime import UTC, datetime, timedelta

import pytest
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base, DailyMaintenanceRun
from app.main import create_app
from app.services.email_sender import CapturedEmailSender
from app.services.maintenance import run_due_maintenance_with


def _db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)()


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


@pytest.mark.anyio
async def test_real_request_triggers_maintenance_but_health_and_assets_do_not() -> None:
    calls = 0

    def maintenance_task() -> None:
        nonlocal calls
        calls += 1

    app = create_app(maintenance_task=maintenance_task)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await client.get("/health")
        await client.get("/assets/missing.css")
        await client.get("/dashboard")

    assert calls == 1
