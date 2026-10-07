"""Application retention dates derived from opening decisions."""

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.time import as_utc, pacific_today
from app.db.models import (
    ApplicantDraft,
    Application,
    ApplicationParticipation,
    Opening,
    OpeningIntakeMode,
    OpeningOutcome,
)


def retention_is_current(application: Application, *, now: datetime | None = None) -> bool:
    """The Pacific purge date is the first day retained data is unavailable."""
    return application.retention_due_on is None or application.retention_due_on > pacific_today(now=now)


def current_retention_clause(*, now: datetime | None = None):
    return or_(Application.retention_due_on.is_(None), Application.retention_due_on > pacific_today(now=now))


def one_year_after(value: date) -> date:
    return years_after(value, 1)


def years_after(value: date, years: int) -> date:
    try:
        return value.replace(year=value.year + years)
    except ValueError:
        return value.replace(year=value.year + years, day=28)


def refresh_application_retention(db: Session, application: Application) -> None:
    """Recompute the legal-retention anchor from durable participation history."""
    participations = db.execute(
        select(ApplicationParticipation, Opening)
        .join(Opening, Opening.id == ApplicationParticipation.opening_id)
        .where(ApplicationParticipation.application_id == application.id)
    ).all()
    if not participations:
        application.retention_due_on = draft_expiry_for_opening_ids(
            db, application.working_opening_ids or []
        )
        return

    selected_decisions = [
        pacific_today(now=opening.decided_at)
        for participation, opening in participations
        if participation.outcome == OpeningOutcome.SELECTED
        and opening.decided_at is not None
    ]
    if selected_decisions:
        application.retention_due_on = years_after(max(selected_decisions), 7)
        _discard_private_working_copy(application)
        return

    decision_dates = [
        pacific_today(now=opening.decided_at)
        for _, opening in participations
        if opening.decided_at is not None
    ]
    application.retention_due_on = (
        one_year_after(max(decision_dates))
        if len(decision_dates) == len(participations)
        else None
    )
    if application.retention_due_on is not None and application.submitted_at is not None:
        _discard_private_working_copy(application)


def _discard_private_working_copy(application: Application) -> None:
    if application.submitted_at is None:
        return
    changed = (
        application.working_answers != application.raw_row
        or application.working_content_hash != application.raw_row_hash
        or bool(application.working_opening_ids)
        or application.working_saved_at is None
        or as_utc(application.working_saved_at) != as_utc(application.submitted_at)
    )
    if changed:
        application.working_revision += 1
    application.working_answers = dict(application.raw_row)
    application.working_content_hash = application.raw_row_hash
    application.working_saved_at = application.submitted_at
    application.working_opening_ids = []


def refresh_draft_retention_for_opening(
    db: Session, opening_id: int, *, now: datetime | None = None,
) -> None:
    """Update current private deadlines after publication or an opening edit.

    Explicit selections follow only their chosen openings; empty selections share
    the latest published close date. An elapsed deadline cannot be revived here.
    The caller holds the opening's write transaction through these updates.
    """
    now = now or datetime.now(UTC)
    today = pacific_today(now=now)
    applications = db.scalars(
        select(Application).where(
            Application.submitted_at.is_(None),
            current_retention_clause(now=now),
        )
    ).all()
    drafts = db.scalars(
        select(ApplicantDraft).where(
            ApplicantDraft.resolved_at.is_(None),
            ApplicantDraft.revoked_at.is_(None),
            ApplicantDraft.expires_on > today,
        )
    ).all()

    fallback_due_on = (draft_expiry_for_opening_ids(db, [])
        if any(not record.working_opening_ids for record in [*applications, *drafts]) else None)
    for application in applications:
        ids = application.working_opening_ids or []
        if not ids:
            application.retention_due_on = fallback_due_on
        elif opening_id in ids:
            application.retention_due_on = draft_expiry_for_opening_ids(db, ids)
    for draft in drafts:
        ids = draft.working_opening_ids or []
        if ids and opening_id not in ids:
            continue
        due_on = draft_expiry_for_opening_ids(db, ids) if ids else fallback_due_on
        if due_on is not None:
            draft.expires_on = due_on


def draft_expiry_for_opening_ids(db: Session, opening_ids: list[int]) -> date | None:
    """Expire an unsubmitted draft once its last available opening has closed."""
    query = select(Opening.application_close_date)
    if opening_ids:
        query = query.where(Opening.id.in_(opening_ids))
    else:
        query = query.where(
            Opening.published_at.is_not(None),
            Opening.intake_mode == OpeningIntakeMode.APPLICATIONS,
        )
    latest_close = db.scalar(query.order_by(Opening.application_close_date.desc()).limit(1))
    return latest_close + timedelta(days=1) if latest_close is not None else None
