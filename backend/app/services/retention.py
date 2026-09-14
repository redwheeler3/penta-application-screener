"""Application retention dates derived from opening decisions."""

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import pacific_today
from app.db.models import (
    ApplicantDraft,
    Application,
    ApplicationParticipation,
    Opening,
    OpeningOutcome,
)


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
    application.working_answers = dict(application.raw_row)
    application.working_content_hash = application.raw_row_hash
    application.working_saved_at = application.submitted_at
    application.working_opening_ids = []


def refresh_draft_retention_for_opening(db: Session, opening_id: int) -> None:
    """Refresh private records whose saved opening selections include one edited opening."""
    applications = db.scalars(
        select(Application).where(Application.submitted_at.is_(None))
    ).all()
    for application in applications:
        if opening_id in (application.working_opening_ids or []):
            refresh_application_retention(db, application)

    drafts = db.scalars(
        select(ApplicantDraft).where(
            ApplicantDraft.resolved_at.is_(None),
            ApplicantDraft.revoked_at.is_(None),
        )
    ).all()
    for draft in drafts:
        if opening_id not in (draft.working_opening_ids or []):
            continue
        due_on = draft_expiry_for_opening_ids(db, draft.working_opening_ids or [])
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
            Opening.application_close_date >= pacific_today(),
        )
    latest_close = db.scalar(query.order_by(Opening.application_close_date.desc()).limit(1))
    return latest_close + timedelta(days=1) if latest_close is not None else None
