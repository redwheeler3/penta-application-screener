"""Capture available applications before an opening changes its retention coverage."""

from datetime import UTC, datetime

from sqlalchemy import delete, exists, select, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from app.db.models import (
    Application,
    ApplicationParticipation,
    Opening,
    OpeningOutcome,
    OpeningRetentionProtection,
)
from app.services.applications.retention import current_retention_clause


def lock_openings(db: Session) -> None:
    """Acquire SQLite's writer even when no opening exists yet."""
    db.execute(update(Opening).where(Opening.id == -1).values(updated_at=Opening.updated_at))


def available_protection_ids(db: Session, *, now: datetime | None = None) -> list[int]:
    now = now or datetime.now(UTC)
    db.flush()
    selected = exists(select(ApplicationParticipation.id).where(
        ApplicationParticipation.application_id == Application.id,
        ApplicationParticipation.outcome == OpeningOutcome.SELECTED))
    return list(db.scalars(select(Application.id).where(
        Application.submitted_at.is_not(None), Application.withdrawn_at.is_(None),
        ~selected, current_retention_clause(now=now))))


def replace_opening_protection(db: Session, opening_id: int, application_ids: list[int]) -> None:
    """The caller captures current identities under the writer before changing dates."""
    db.execute(delete(OpeningRetentionProtection).where(OpeningRetentionProtection.opening_id == opening_id))
    if application_ids:
        db.execute(insert(OpeningRetentionProtection), [
            {"opening_id": opening_id, "application_id": identity} for identity in application_ids])
