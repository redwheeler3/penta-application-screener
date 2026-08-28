"""Completely remove aggregates whose retention period has ended."""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.time import pacific_today
from app.db.models import (
    ApplicantDraft,
    Application,
    ApplicationParticipation,
    Feedback,
    OpeningOutcome,
    RetentionDeletion,
)


@dataclass(frozen=True)
class PurgeSummary:
    applications_purged: int = 0
    drafts_purged: int = 0


def purge_due_applicant_data(db: Session, *, now: datetime | None = None) -> PurgeSummary:
    """Purge all records due on the Pacific date, retaining only deletion facts."""
    now = now or datetime.now(UTC)
    today = pacific_today(now=now)
    applications_purged = 0
    drafts_purged = 0

    applications = db.scalars(
        select(Application)
        .where(
            Application.retention_due_on.is_not(None),
            Application.retention_due_on <= today,
        )
        .order_by(Application.id)
    ).all()
    for application in applications:
        due_on = application.retention_due_on
        if due_on is None:
            continue
        retention_rule = _application_retention_rule(db, application.id)
        _record_deletion(
            db,
            record_kind="application",
            record_id=application.id,
            retention_rule=retention_rule,
            due_on=due_on,
            now=now,
        )
        db.execute(
            update(Feedback)
            .where(Feedback.applicant_id == application.id)
            .values(applicant_id=None)
        )
        db.delete(application)
        db.commit()
        applications_purged += 1

    drafts = db.scalars(
        select(ApplicantDraft)
        .where(
            ApplicantDraft.application_id.is_(None),
            ApplicantDraft.retention_due_on <= today,
        )
        .order_by(ApplicantDraft.id)
    ).all()
    for draft in drafts:
        _record_deletion(
            db,
            record_kind="applicant_draft",
            record_id=draft.id,
            retention_rule="one_year",
            due_on=draft.retention_due_on,
            now=now,
        )
        db.delete(draft)
        db.commit()
        drafts_purged += 1

    return PurgeSummary(
        applications_purged=applications_purged,
        drafts_purged=drafts_purged,
    )


def _application_retention_rule(db: Session, application_id: int) -> str:
    selected = db.scalar(
        select(ApplicationParticipation.id).where(
            ApplicationParticipation.application_id == application_id,
            ApplicationParticipation.outcome == OpeningOutcome.SELECTED,
        )
    )
    return "selected_seven_years" if selected is not None else "one_year"


def _record_deletion(
    db: Session,
    *,
    record_kind: str,
    record_id: int,
    retention_rule: str,
    due_on,
    now: datetime,
) -> None:
    db.add(
        RetentionDeletion(
            record_kind=record_kind,
            record_id=record_id,
            retention_rule=retention_rule,
            due_on=due_on,
            deleted_at=now,
        )
    )
