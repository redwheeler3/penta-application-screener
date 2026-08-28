"""Fill an opening from retained previous applicants without launching intake."""

from datetime import UTC, datetime

from sqlalchemy import Select, exists, func, not_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.problems import Problem
from app.core.time import pacific_today
from app.db.models import (
    Application,
    ApplicationParticipation,
    Opening,
    OpeningIntakeMode,
    OpeningOutcome,
    User,
)
from app.schemas.openings import DirectSelectionOpeningCreate
from app.services.retention import refresh_application_retention


def available_previous_applicants_query() -> Select[tuple[Application]]:
    participated = exists(
        select(ApplicationParticipation.id).where(
            ApplicationParticipation.application_id == Application.id
        )
    )
    selected = exists(
        select(ApplicationParticipation.id).where(
            ApplicationParticipation.application_id == Application.id,
            ApplicationParticipation.outcome == OpeningOutcome.SELECTED,
        )
    )
    return select(Application).where(
        Application.submitted_at.is_not(None),
        Application.withdrawn_at.is_(None),
        Application.retention_due_on >= pacific_today(),
        participated,
        not_(selected),
    )


def search_previous_applicants(
    db: Session, query: str, *, limit: int = 25
) -> list[Application]:
    terms = query.casefold().split()
    statement = available_previous_applicants_query()
    for term in terms:
        statement = statement.where(
            or_(
                func.lower(Application.applicant_name).contains(term, autoescape=True),
                func.lower(Application.primary_email).contains(term, autoescape=True),
            )
        )
    return list(
        db.scalars(
            statement.order_by(Application.applicant_name, Application.id).limit(limit)
        ).all()
    )


def available_previous_applicant(
    db: Session, application_id: int
) -> Application | None:
    return db.scalar(
        available_previous_applicants_query().where(Application.id == application_id)
    )


def create_direct_selection_opening(
    db: Session,
    values: DirectSelectionOpeningCreate,
    *,
    decided_by: User,
    now: datetime | None = None,
) -> Opening:
    now = now or datetime.now(UTC)
    if values.move_in_date <= pacific_today(now=now):
        raise Problem("invalid_settings", detail="The move-in date must be in the future.")
    application = available_previous_applicant(db, values.application_id)
    if application is None:
        raise Problem(
            "invalid_settings",
            detail="Choose an available retained applicant.",
        )

    opening = Opening(
        intake_mode=OpeningIntakeMode.DIRECT_SELECTION,
        unit_size_bedrooms=values.unit_size_bedrooms,
        housing_charge_cents=values.housing_charge_cents,
        application_open_date=None,
        application_close_date=None,
        move_in_date=values.move_in_date,
        published_at=None,
    )
    db.add(opening)
    db.flush()
    try:
        db.add(
            ApplicationParticipation(
                application_id=application.id,
                opening_id=opening.id,
                applied_at=now,
                outcome=OpeningOutcome.SELECTED,
                outcome_decided_at=now,
                outcome_decided_by_user_id=decided_by.id,
            )
        )
        db.flush()
        refresh_application_retention(db, application)
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise Problem(
            "invalid_settings",
            detail="That applicant was selected elsewhere. Search again.",
        ) from error
    db.refresh(opening)
    return opening


def remove_direct_selection_opening(db: Session, opening: Opening) -> None:
    if opening.intake_mode != OpeningIntakeMode.DIRECT_SELECTION:
        raise Problem("invalid_settings", detail="This is not a direct-selection opening.")
    if opening.move_in_date <= pacific_today():
        raise Problem(
            "invalid_settings",
            detail="A direct selection is permanent after the move-in date.",
        )
    participation = db.scalar(
        select(ApplicationParticipation).where(
            ApplicationParticipation.opening_id == opening.id,
            ApplicationParticipation.outcome == OpeningOutcome.SELECTED,
        )
    )
    if participation is None:
        raise Problem("invalid_settings", detail="This opening has no selected applicant.")
    application = db.get(Application, participation.application_id)
    db.delete(participation)
    db.flush()
    db.delete(opening)
    db.flush()
    if application is not None:
        refresh_application_retention(db, application)
    db.commit()
