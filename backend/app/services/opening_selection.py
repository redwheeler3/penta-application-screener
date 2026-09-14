"""Committee-owned opening selection with a closed-to-archived finality boundary."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.problems import Problem
from app.core.time import pacific_today
from app.db.models import (
    Application,
    ApplicationParticipation,
    Opening,
    OpeningOutcome,
    OpeningPhase,
    User,
)
from app.services.openings import opening_phase
from app.services.retention import refresh_application_retention
from app.services.selected_application import (
    revoke_selected_applicant_access,
    selected_opening_id,
)


def active_opening_participants(
    db: Session, opening: Opening
) -> list[tuple[ApplicationParticipation, Application]]:
    return list(
        db.execute(
            select(ApplicationParticipation, Application)
            .join(Application, Application.id == ApplicationParticipation.application_id)
            .where(
                ApplicationParticipation.opening_id == opening.id,
                ApplicationParticipation.withdrawn_at.is_(None),
                Application.submitted_at.is_not(None),
                Application.withdrawn_at.is_(None),
            )
            .order_by(Application.applicant_name, Application.id)
        ).all()
    )


def selectable_opening_candidates(
    db: Session, opening: Opening
) -> list[tuple[ApplicationParticipation, Application]]:
    return [
        (participation, application)
        for participation, application in active_opening_participants(db, opening)
        if selected_opening_id(db, application.id) is None
    ]


def selected_participation(
    db: Session, opening_id: int
) -> ApplicationParticipation | None:
    return db.scalar(
        select(ApplicationParticipation).where(
            ApplicationParticipation.opening_id == opening_id,
            ApplicationParticipation.outcome == OpeningOutcome.SELECTED,
        )
    )


def require_ai_actions_available(db: Session, opening_id: int) -> Opening:
    """Reject paid AI work after the committee archives an opening."""
    opening = db.get(Opening, opening_id)
    if opening is None:
        raise Problem("not_found", detail="Opening not found.")
    if opening_phase(opening) == OpeningPhase.ARCHIVED:
        raise Problem(
            "opening_finalized",
            detail="Screening and ranking are closed because this archived opening has a final outcome.",
        )
    return opening


def overdue_openings_needing_decision(db: Session) -> list[Opening]:
    openings = db.scalars(
        select(Opening)
        .where(
            Opening.published_at.is_not(None),
            Opening.move_in_date <= pacific_today(),
            Opening.decided_at.is_(None),
        )
        .order_by(Opening.move_in_date, Opening.id)
    ).all()
    return [opening for opening in openings if active_opening_participants(db, opening)]


def confirm_opening_selection(
    db: Session,
    opening: Opening,
    application_id: int,
    *,
    decided_by: User,
    now: datetime | None = None,
) -> None:
    existing = selected_participation(db, opening.id)
    if opening.decided_at is not None:
        if existing is not None and existing.application_id == application_id:
            return
        raise Problem("invalid_settings", detail="The opening decision is permanent.")
    _require_selection_available(opening)
    now = now or datetime.now(UTC)
    participants = active_opening_participants(db, opening)
    selected_candidate = next(
        (
            participation
            for participation, application in selectable_opening_candidates(db, opening)
            if application.id == application_id
        ),
        None,
    )
    if selected_candidate is None:
        raise Problem(
            "invalid_settings",
            detail="Choose an active applicant from this opening.",
        )

    other_opening_id = selected_opening_id(db, application_id)
    if other_opening_id is not None:
        raise Problem(
            "invalid_settings",
            detail="This applicant has already been selected for another opening.",
        )

    affected_applications: list[Application] = []
    for participation, application in participants:
        participation.outcome = (
            OpeningOutcome.SELECTED
            if application.id == application_id
            else OpeningOutcome.UNSUCCESSFUL
        )
        participation.unsuccessful_notified_at = None
        affected_applications.append(application)

    opening.decided_at = now
    opening.decided_by_user_id = decided_by.id
    opening.no_household_selected = False
    for application in affected_applications:
        refresh_application_retention(db, application)
    revoke_selected_applicant_access(db, application_id, now=now)
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise Problem(
            "invalid_settings",
            detail="Another opening selection was saved first. Review the openings and try again.",
        ) from error


def confirm_no_household_selected(
    db: Session,
    opening: Opening,
    *,
    decided_by: User,
    now: datetime | None = None,
) -> None:
    if opening.decided_at is not None:
        if opening.no_household_selected:
            return
        raise Problem("invalid_settings", detail="The opening decision is permanent.")
    _require_selection_available(opening)

    now = now or datetime.now(UTC)
    affected_applications: list[Application] = []
    for participation, application in active_opening_participants(db, opening):
        participation.outcome = OpeningOutcome.UNSUCCESSFUL
        participation.unsuccessful_notified_at = None
        affected_applications.append(application)
    opening.decided_at = now
    opening.decided_by_user_id = decided_by.id
    opening.no_household_selected = True
    for application in affected_applications:
        refresh_application_retention(db, application)
    db.commit()


def _require_selection_available(opening: Opening) -> None:
    phase = opening_phase(opening)
    if phase != OpeningPhase.CLOSED:
        raise Problem(
            "invalid_settings",
            detail="Select the successful applicant after applications close.",
        )
