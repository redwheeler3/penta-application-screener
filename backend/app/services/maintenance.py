"""Lease and run lifecycle work at most once per Pacific calendar day."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.time import as_utc, pacific_today
from app.db.models import DailyMaintenanceRun
from app.db.session import SessionLocal
from app.services.email_outbox import retry_queued_emails
from app.services.email_sender import EmailSender, get_email_sender
from app.services.opening_notifications import send_due_unsuccessful_notices
from app.services.retention_purge import purge_due_applicant_data

DAILY_LIFECYCLE_TASK = "applicant_lifecycle"
LEASE_DURATION = timedelta(minutes=10)


def run_due_maintenance() -> None:
    """Entry point for the request background task; failures remain retryable."""
    db = SessionLocal()
    try:
        run_due_maintenance_with(db, get_email_sender())
    finally:
        db.close()


def run_due_maintenance_with(
    db: Session, sender: EmailSender, *, now: datetime | None = None
) -> bool:
    """Claim today's lease and run the ordered, idempotent lifecycle sweep."""
    now = now or datetime.now(UTC)
    run = _claim_daily_run(db, now=now)
    if run is None:
        return False
    try:
        retry_queued_emails(db, sender, now=now)
        send_due_unsuccessful_notices(db, sender, now=now)
        purge_due_applicant_data(db, sender, now=now)
    except Exception as error:
        run.status = "failed"
        run.lease_expires_at = now + LEASE_DURATION
        run.last_error_code = type(error).__name__[:120]
        db.commit()
        return False
    run.status = "completed"
    run.completed_at = now
    run.last_error_code = None
    db.commit()
    return True


def _claim_daily_run(db: Session, *, now: datetime) -> DailyMaintenanceRun | None:
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
        )
        db.commit()
        if claimed.rowcount != 1:
            return None
        db.refresh(existing)
        return existing

    run = DailyMaintenanceRun(
        task=DAILY_LIFECYCLE_TASK,
        pacific_date=today,
        status="running",
        lease_expires_at=now + LEASE_DURATION,
        attempt_count=1,
    )
    db.add(run)
    try:
        db.commit()
        db.refresh(run)
        return run
    except IntegrityError:
        db.rollback()
        return None
