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


@pytest.mark.parametrize(("send_seconds", "cross_midnight"), [(1, False), (10, False), (10, True)])
def test_daily_owner_is_renewed_through_long_retry_batches(monkeypatch, send_seconds, cross_midnight):
    from app.core.time import PACIFIC, pacific_today
    from app.db.models import Opening
    from app.services.email import outbox
    from app.services.email.sender import EmailRetryableError
    from app.services.openings.subscriptions import save_subscription
    from app.services.openings.vacancy_notifications import (
        opening_audience,
        queue_opening_notifications,
    )
    from tests.applicant.support import app_and_db

    _app, db, _sender = app_and_db()
    opening = db.scalar(select(Opening))
    for index in range(100):
        save_subscription(db, email=f"fiction-{index}@example.com", unit_sizes={2}, source="test")
    queue_opening_notifications(db, opening, opening_audience(db, 2))
    db.commit()

    class Clock(datetime):
        value = datetime.combine(pacific_today(), datetime.min.time(), tzinfo=PACIFIC).astimezone(UTC) + timedelta(
            minutes=-1 if cross_midnight else 60)
        @classmethod
        def now(cls, tz=None):
            return cls.value if tz else cls.value.replace(tzinfo=None)

    class SlowFailure:
        calls = 0
        second_claimed = None
        def send(self, _message):
            self.calls += 1
            Clock.value += timedelta(seconds=send_seconds)
            if self.calls == 65:
                with sessionmaker(bind=db.bind)() as other:
                    self.second_claimed = maintenance._claim_daily_run(other, now=Clock.value)
            raise EmailRetryableError("Synthetic timeout")

    monkeypatch.setattr(maintenance, "datetime", Clock)
    monkeypatch.setattr(outbox, "datetime", Clock)
    sender = SlowFailure()
    assert run_due_maintenance_with(db, sender)
    assert sender.calls == 100
    assert sender.second_claimed is None
    run = db.scalar(select(DailyMaintenanceRun).execution_options(populate_existing=True))
    assert run.attempt_count == 1
    assert run.status == "completed"
    assert run.completed_at == Clock.value.replace(tzinfo=None)


@pytest.mark.parametrize("accepted", [False, True])
def test_replaced_daily_owner_stops_before_dispatching_another_email(accepted):
    from app.db.models import Opening
    from app.services.email.sender import EmailRetryableError
    from app.services.openings.subscriptions import save_subscription
    from app.services.openings.vacancy_notifications import (
        opening_audience,
        queue_opening_notifications,
    )
    from tests.applicant.support import app_and_db

    _app, db, _sender = app_and_db()
    now = datetime.now(UTC)
    opening = db.scalar(select(Opening))
    for index in range(2):
        save_subscription(db, email=f"fiction-{index}@example.com", unit_sizes={2}, source="test")
    queue_opening_notifications(db, opening, opening_audience(db, 2))
    db.commit()
    calls = []
    replacement = []

    class ReplacedDuringSend:
        def send(self, message):
            calls.append(message.to)
            with sessionmaker(bind=db.bind)() as other:
                replacement.append(maintenance._claim_daily_run(other, now=now + timedelta(minutes=11)))
            if accepted:
                return "captured"
            raise EmailRetryableError("Synthetic failure")

    assert not run_due_maintenance_with(db, ReplacedDuringSend(), now=now)
    assert replacement[0] is not None
    assert len(calls) == 1
    run = db.scalar(select(DailyMaintenanceRun).execution_options(populate_existing=True))
    assert run.attempt_count == 2
    assert run.status == "running"
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


def test_abandoned_previous_day_lease_expires_before_new_day_starts():
    from app.core.time import PACIFIC

    midnight = datetime(2026, 11, 25, tzinfo=PACIFIC).astimezone(UTC)
    db = _db()
    assert maintenance._claim_daily_run(db, now=midnight - timedelta(minutes=1))
    assert maintenance._claim_daily_run(db, now=midnight) is None
    assert maintenance._claim_daily_run(db, now=midnight + timedelta(minutes=10))
