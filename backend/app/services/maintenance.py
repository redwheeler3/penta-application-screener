"""Lease and run lifecycle work at most once per Pacific calendar day."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.time import as_utc, pacific_today
from app.db.models import DailyMaintenanceRun
from app.db.session import SessionLocal
from app.services.applications.purge import purge_due_applicant_data
from app.services.email.outbox import (
    purge_expired_vacancy_delivery_failures,
    retry_queued_emails,
)
from app.services.email.sender import EmailSender, get_email_sender
from app.services.openings.notifications import queue_due_unsuccessful_notices

DAILY_LIFECYCLE_TASK = "applicant_lifecycle"
LEASE_DURATION = timedelta(minutes=10)


@dataclass(frozen=True)
class MaintenanceLease:
    run_id: int
    attempt_count: int


def get_outbox_runner() -> Callable[[EmailSender], None]:
    return run_email_outbox


def run_due_maintenance() -> None:
    """Entry point for the request background task; failures remain retryable."""
    db = SessionLocal()
    try:
        run_due_maintenance_with(db)
    finally:
        db.close()


def run_email_outbox(sender: EmailSender | None = None) -> None:
    """Drain durable email intents after a write without waiting for the daily sweep."""
    db = SessionLocal()
    try:
        retry_queued_emails(db, sender or get_email_sender())
    finally:
        db.close()


def run_due_maintenance_with(
    db: Session, sender: EmailSender | None = None, *, now: datetime | None = None
) -> bool:
    """Claim today's lease and run the ordered, idempotent lifecycle sweep."""
    retry_time = now
    now = now or datetime.now(UTC)
    lease = _claim_daily_run(db, now=now)
    if lease is None:
        return False
    try:
        purge_due_applicant_data(db, now=now)
        queue_due_unsuccessful_notices(db, now=now)
        retry_queued_emails(db, sender or get_email_sender(), now=retry_time)
        purge_expired_vacancy_delivery_failures(db, now=now)
    except Exception as error:
        db.rollback()
        _finish_daily_run(db, lease, now=now, error_code=type(error).__name__[:120])
        return False
    return _finish_daily_run(db, lease, now=now)


def _finish_daily_run(
    db: Session, lease: MaintenanceLease, *, now: datetime, error_code: str | None = None
) -> bool:
    values = {"status": "completed", "completed_at": now, "last_error_code": None}
    if error_code is not None:
        values = {"status": "failed", "lease_expires_at": now + LEASE_DURATION, "last_error_code": error_code}
    finished = db.execute(update(DailyMaintenanceRun).where(
        DailyMaintenanceRun.id == lease.run_id,
        DailyMaintenanceRun.attempt_count == lease.attempt_count,
        DailyMaintenanceRun.status == "running",
    ).values(**values).execution_options(synchronize_session=False))
    db.commit()
    return finished.rowcount == 1


def _claim_daily_run(db: Session, *, now: datetime) -> MaintenanceLease | None:
    today = pacific_today(now=now)
    existing = db.scalar(
        select(DailyMaintenanceRun).where(
            DailyMaintenanceRun.task == DAILY_LIFECYCLE_TASK,
            DailyMaintenanceRun.pacific_date == today,
        )
    )
    if existing is not None and (
        existing.status == "completed" or as_utc(existing.lease_expires_at) > now
    ):
        return None
    if existing is not None:
        claimed = db.execute(
            update(DailyMaintenanceRun)
            .where(
                DailyMaintenanceRun.id == existing.id,
                DailyMaintenanceRun.status != "completed",
                DailyMaintenanceRun.lease_expires_at <= now,
            )
            .values(
                status="running",
                lease_expires_at=now + LEASE_DURATION,
                attempt_count=DailyMaintenanceRun.attempt_count + 1,
                last_error_code=None,
            )
            .returning(DailyMaintenanceRun.id, DailyMaintenanceRun.attempt_count)
            .execution_options(synchronize_session=False)
        ).one_or_none()
        db.commit()
        return MaintenanceLease(*claimed) if claimed is not None else None

    run = DailyMaintenanceRun(
        task=DAILY_LIFECYCLE_TASK,
        pacific_date=today,
        status="running",
        lease_expires_at=now + LEASE_DURATION,
        attempt_count=1,
    )
    db.add(run)
    try:
        db.flush()
        lease = MaintenanceLease(run.id, run.attempt_count)
        db.commit()
        return lease
    except IntegrityError:
        db.rollback()
        return None
