"""Applicant selection rules for published openings."""

from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.problems import Problem
from app.core.time import pacific_today
from app.db.models import Application, ApplicationParticipation, Opening, OpeningPhase
from app.services.openings import opening_phase
from app.services.retention import one_year_after


@dataclass(frozen=True)
class ApplicantOpeningState:
    opening: Opening
    phase: OpeningPhase
    selected: bool
    participating: bool
    has_participated: bool

    @property
    def can_select(self) -> bool:
        return self.phase == OpeningPhase.OPEN or (
            self.phase == OpeningPhase.CLOSED and self.participating
        )

    @property
    def can_withdraw(self) -> bool:
        return self.selected and self.phase in {OpeningPhase.OPEN, OpeningPhase.CLOSED}


def applicant_opening_states(
    db: Session,
    application: Application | None,
    *,
    today: date | None = None,
    use_working_copy: bool = False,
) -> list[ApplicantOpeningState]:
    current_date = today or pacific_today()
    participating_ids = _selected_opening_ids(db, application)
    historical_ids = _participation_ids(db, application)
    selected_ids = participating_ids
    if (
        use_working_copy
        and application is not None
        and application.working_opening_ids is not None
    ):
        selected_ids = set(application.working_opening_ids)
    openings = db.scalars(
        select(Opening)
        .where(Opening.published_at.is_not(None))
        .order_by(Opening.move_in_date, Opening.id)
    ).all()
    states = []
    for opening in openings:
        phase = opening_phase(opening, today=current_date)
        participating = opening.id in participating_ids
        states.append(
            ApplicantOpeningState(
                opening=opening,
                phase=phase,
                # A pending private withdrawal becomes immaterial once the move-in date
                # archives the participation and makes that history immutable.
                selected=(
                    opening.id in selected_ids
                    or (phase == OpeningPhase.ARCHIVED and participating)
                ),
                participating=participating,
                has_participated=opening.id in historical_ids,
            )
        )
    return [
        state
        for state in states
        if state.phase != OpeningPhase.ARCHIVED or state.participating
    ]


def opening_ids_by_application(
    db: Session,
    application_ids: list[int],
) -> dict[int, list[int]]:
    opening_ids = {application_id: [] for application_id in application_ids}
    if not application_ids:
        return opening_ids
    rows = db.execute(
        select(
            ApplicationParticipation.application_id,
            Opening.id,
        )
        .join(Opening, Opening.id == ApplicationParticipation.opening_id)
        .where(
            ApplicationParticipation.application_id.in_(application_ids),
            ApplicationParticipation.withdrawn_at.is_(None),
        )
        .order_by(Opening.move_in_date, Opening.id)
    )
    for application_id, opening_id in rows:
        opening_ids[application_id].append(opening_id)
    return opening_ids


def application_is_editable(states: list[ApplicantOpeningState]) -> bool:
    return any(
        state.phase == OpeningPhase.OPEN
        or (state.participating and state.phase == OpeningPhase.CLOSED)
        for state in states
    )


def validate_opening_selection(
    db: Session,
    application: Application | None,
    requested_ids: list[int],
    *,
    now: datetime | None = None,
) -> list[Opening]:
    return _validate_opening_selection(
        db,
        application,
        requested_ids,
        now=now,
        require_selection=True,
    )


def validate_working_opening_selection(
    db: Session,
    application: Application | None,
    requested_ids: list[int],
    *,
    now: datetime | None = None,
) -> list[Opening]:
    return _validate_opening_selection(
        db,
        application,
        requested_ids,
        now=now,
        require_selection=False,
    )


def _validate_opening_selection(
    db: Session,
    application: Application | None,
    requested_ids: list[int],
    *,
    now: datetime | None,
    require_selection: bool,
) -> list[Opening]:
    if len(requested_ids) != len(set(requested_ids)):
        raise Problem("invalid_opening_selection", detail="Choose each opening only once.")

    today = pacific_today(now=now)
    states = applicant_opening_states(db, application, today=today)
    by_id = {state.opening.id: state for state in states}
    requested = set(requested_ids)
    selected = {state.opening.id for state in states if state.selected}

    if requested - set(by_id):
        raise Problem(
            "invalid_opening_selection",
            detail="One or more selected openings are not available.",
        )
    for opening_id in requested - selected:
        if not by_id[opening_id].can_select:
            raise Problem(
                "applications_closed",
                detail="That opening is no longer accepting applications.",
            )
    for opening_id in selected - requested:
        if not by_id[opening_id].can_withdraw:
            raise Problem(
                "opening_archived",
                detail="Your choice for this opening cannot be changed after the move-in date.",
            )
    current_requested = {
        opening_id
        for opening_id in requested
        if by_id[opening_id].phase != OpeningPhase.ARCHIVED
    }
    current_selected = {
        opening_id
        for opening_id in selected
        if by_id[opening_id].phase != OpeningPhase.ARCHIVED
    }
    withdrawing = current_selected - current_requested
    if require_selection and not current_requested and not withdrawing:
        raise Problem(
            "opening_selection_required",
            detail="Choose at least one opening before submitting.",
        )
    return [by_id[opening_id].opening for opening_id in requested_ids]


def apply_opening_selection(
    db: Session,
    application: Application,
    selected_openings: list[Opening],
    *,
    submitted_at: datetime,
) -> None:
    existing = {
        participation.opening_id: participation
        for participation in db.scalars(
            select(ApplicationParticipation).where(
                ApplicationParticipation.application_id == application.id
            )
        )
    }
    selected_ids = {opening.id for opening in selected_openings}
    for opening_id, participation in existing.items():
        if participation.withdrawn_at is None and opening_id not in selected_ids:
            participation.withdrawn_at = submitted_at
    for opening in selected_openings:
        participation = existing.get(opening.id)
        if participation is None:
            db.add(
                ApplicationParticipation(
                    application_id=application.id,
                    opening_id=opening.id,
                    applied_at=submitted_at,
                )
            )
        else:
            participation.withdrawn_at = None

    all_move_in_dates = list(
        db.scalars(
            select(Opening.move_in_date)
            .join(
                ApplicationParticipation,
                ApplicationParticipation.opening_id == Opening.id,
            )
            .where(ApplicationParticipation.application_id == application.id)
        )
    )
    all_move_in_dates.extend(
        opening.move_in_date for opening in selected_openings if opening.id not in existing
    )
    if all_move_in_dates:
        application.retention_due_on = one_year_after(max(all_move_in_dates))


def _selected_opening_ids(db: Session, application: Application | None) -> set[int]:
    if application is None or application.id is None:
        return set()
    return set(
        db.scalars(
            select(ApplicationParticipation.opening_id).where(
                ApplicationParticipation.application_id == application.id,
                ApplicationParticipation.withdrawn_at.is_(None),
            )
        )
    )


def _participation_ids(db: Session, application: Application | None) -> set[int]:
    if application is None or application.id is None:
        return set()
    return set(
        db.scalars(
            select(ApplicationParticipation.opening_id).where(
                ApplicationParticipation.application_id == application.id,
            )
        )
    )
