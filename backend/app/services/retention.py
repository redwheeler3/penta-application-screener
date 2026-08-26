"""Application retention dates derived from recorded opening participation."""

from datetime import date

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
        application.retention_due_on = retention_due_for_opening_ids(
            db, application.working_opening_ids or []
        )
        return

    selected_move_ins = [
        opening.move_in_date
        for participation, opening in participations
        if participation.outcome == OpeningOutcome.SELECTED
    ]
    if selected_move_ins:
        application.retention_due_on = years_after(max(selected_move_ins), 7)
        return

    application.retention_due_on = one_year_after(
        max(opening.move_in_date for _, opening in participations)
    )


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
        due_on = retention_due_for_opening_ids(db, draft.working_opening_ids or [])
        if due_on is not None:
            draft.retention_due_on = due_on


def retention_due_for_opening_ids(db: Session, opening_ids: list[int]) -> date | None:
    query = select(Opening.move_in_date)
    if opening_ids:
        query = query.where(Opening.id.in_(opening_ids))
    else:
        # Save-and-return-later accepts an incomplete draft before the applicant has
        # chosen an opening. Anchor it to the latest currently available offering.
        query = query.where(
            Opening.published_at.is_not(None),
            Opening.move_in_date > pacific_today(),
        )
    latest_move_in = db.scalar(query.order_by(Opening.move_in_date.desc()).limit(1))
    return one_year_after(latest_move_in) if latest_move_in is not None else None
