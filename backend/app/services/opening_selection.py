"""Committee-owned opening selection with a closed-to-archived finality boundary."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.problems import Problem
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
                Application.deleted_at.is_(None),
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


def selected_opening_id(db: Session, application_id: int) -> int | None:
    return db.scalar(
        select(ApplicationParticipation.opening_id).where(
            ApplicationParticipation.application_id == application_id,
            ApplicationParticipation.outcome == OpeningOutcome.SELECTED,
        )
    )


def opening_decision_exists(db: Session, opening: Opening) -> bool:
    return (
        opening.no_household_selected_at is not None
        or selected_participation(db, opening.id) is not None
    )


def archived_openings_needing_selection(db: Session) -> list[Opening]:
    openings = db.scalars(
        select(Opening)
        .where(
            Opening.published_at.is_not(None),
            Opening.move_in_date <= pacific_today(),
        )
        .order_by(Opening.move_in_date, Opening.id)
    ).all()
    return [
        opening
        for opening in openings
        if not opening_decision_exists(db, opening)
        and active_opening_participants(db, opening)
    ]


def confirm_opening_selection(
    db: Session,
    opening: Opening,
    application_id: int,
    *,
    decided_by: User,
    now: datetime | None = None,
) -> None:
    phase = _selection_phase(opening)
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

    existing = selected_participation(db, opening.id)
    if opening.no_household_selected_at is not None:
        if phase == OpeningPhase.ARCHIVED:
            raise Problem(
                "invalid_settings",
                detail="The archived opening decision is permanent.",
            )
        raise Problem(
            "invalid_settings",
            detail="Undo the current decision before choosing an applicant.",
        )
    if existing is not None:
        if existing.application_id == application_id:
            return
        if phase == OpeningPhase.ARCHIVED:
            raise Problem(
                "invalid_settings",
                detail="The selected applicant is permanent after the opening is archived.",
            )
        raise Problem(
            "invalid_settings",
            detail="Undo the current selection before choosing another applicant.",
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
        participation.outcome_decided_at = now
        participation.outcome_decided_by_user_id = decided_by.id
        participation.unsuccessful_notified_at = None
        affected_applications.append(application)

    for application in affected_applications:
        refresh_application_retention(db, application)
    opening.no_household_selected_at = None
    opening.no_household_selected_by_user_id = None
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
    phase = _selection_phase(opening)
    if opening.no_household_selected_at is not None:
        return
    if selected_participation(db, opening.id) is not None:
        if phase == OpeningPhase.ARCHIVED:
            raise Problem(
                "invalid_settings",
                detail="The archived opening decision is permanent.",
            )
        raise Problem(
            "invalid_settings",
            detail="Undo the current selection before recording no household selected.",
        )

    now = now or datetime.now(UTC)
    affected_applications: list[Application] = []
    for participation, application in active_opening_participants(db, opening):
        participation.outcome = OpeningOutcome.UNSUCCESSFUL
        participation.outcome_decided_at = now
        participation.outcome_decided_by_user_id = decided_by.id
        participation.unsuccessful_notified_at = None
        affected_applications.append(application)
    opening.no_household_selected_at = now
    opening.no_household_selected_by_user_id = decided_by.id
    for application in affected_applications:
        refresh_application_retention(db, application)
    db.commit()


def undo_opening_selection(db: Session, opening: Opening) -> None:
    if opening_phase(opening) != OpeningPhase.CLOSED:
        raise Problem(
            "invalid_settings",
            detail="A selection can be undone only while the opening is closed.",
        )
    if not opening_decision_exists(db, opening):
        return

    affected_applications: list[Application] = []
    for participation, application in active_opening_participants(db, opening):
        participation.outcome = None
        participation.outcome_decided_at = None
        participation.outcome_decided_by_user_id = None
        participation.unsuccessful_notified_at = None
        affected_applications.append(application)
    for application in affected_applications:
        refresh_application_retention(db, application)
    opening.no_household_selected_at = None
    opening.no_household_selected_by_user_id = None
    db.commit()


def _selection_phase(opening: Opening) -> OpeningPhase:
    phase = opening_phase(opening)
    if phase not in {OpeningPhase.CLOSED, OpeningPhase.ARCHIVED}:
        raise Problem(
            "invalid_settings",
            detail="Select the successful applicant after applications close.",
        )
    return phase
