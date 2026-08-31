"""Opening-scoped submitted application pools."""

from sqlalchemy import Select, exists, or_, select
from sqlalchemy.orm import Session, aliased

from app.core.problems import Problem
from app.core.time import pacific_today
from app.db.models import (
    Application,
    ApplicationParticipation,
    Opening,
    OpeningIntakeMode,
    OpeningOutcome,
)


def _retained_application() -> tuple:
    return (
        Application.submitted_at.is_not(None),
        Application.withdrawn_at.is_(None),
        or_(
            Application.retention_due_on.is_(None),
            Application.retention_due_on >= pacific_today(),
        ),
    )


def _selected_application():
    selected = aliased(ApplicationParticipation)
    return exists(
        select(selected.id).where(
            selected.application_id == Application.id,
            selected.outcome == OpeningOutcome.SELECTED,
        )
    ).correlate(Application)


def opening_ai_applications_query(opening_id) -> Select[tuple[Application]]:
    """Non-selected retained applicants that Screen and Rank may use for one opening."""
    return (
        select(Application)
        .join(
            ApplicationParticipation,
            ApplicationParticipation.application_id == Application.id,
        )
        .where(
            *_retained_application(),
            ApplicationParticipation.opening_id == opening_id,
            ApplicationParticipation.withdrawn_at.is_(None),
            ~_selected_application(),
        )
    )


def opening_ai_applications(db: Session, opening_id: int) -> list[Application]:
    return list(
        db.scalars(opening_ai_applications_query(opening_id).order_by(Application.id)).all()
    )


def opening_applications_query(opening_id: int) -> Select[tuple[Application]]:
    """Committee-visible retained applicants for one opening.

    A household selected in this opening remains visible. A household selected in a
    different opening is excluded from this opening's universe.
    """
    selected = aliased(ApplicationParticipation)
    selected_elsewhere = exists(
        select(selected.id).where(
            selected.application_id == Application.id,
            selected.outcome == OpeningOutcome.SELECTED,
            selected.opening_id != opening_id,
        )
    ).correlate(Application)
    return (
        select(Application)
        .join(
            ApplicationParticipation,
            ApplicationParticipation.application_id == Application.id,
        )
        .where(
            *_retained_application(),
            ApplicationParticipation.opening_id == opening_id,
            ApplicationParticipation.withdrawn_at.is_(None),
            ~selected_elsewhere,
        )
    )


def opening_applications(db: Session, opening_id: int) -> list[Application]:
    return list(db.scalars(opening_applications_query(opening_id).order_by(Application.id)).all())


def opening_application(
    db: Session, opening_id: int, application_id: int
) -> Application | None:
    return db.scalar(
        opening_applications_query(opening_id).where(Application.id == application_id)
    )


def visible_committee_openings(db: Session) -> list[Opening]:
    """Openings kept alive by at least one retained non-selected applicant."""
    candidate_exists = exists(
        select(ApplicationParticipation.id)
        .join(Application, Application.id == ApplicationParticipation.application_id)
        .where(
            ApplicationParticipation.opening_id == Opening.id,
            ApplicationParticipation.withdrawn_at.is_(None),
            *_retained_application(),
            ~_selected_application(),
        )
    )
    return list(
        db.scalars(
            select(Opening)
            .where(
                Opening.published_at.is_not(None),
                Opening.intake_mode == OpeningIntakeMode.APPLICATIONS,
                candidate_exists,
            )
            .order_by(Opening.move_in_date, Opening.id)
        ).all()
    )


def resolve_visible_opening_id(db: Session, opening_id: int | None) -> int:
    """Resolve an explicit opening, or the sole visible opening when unambiguous."""
    openings = visible_committee_openings(db)
    visible_ids = {opening.id for opening in openings}
    if opening_id in visible_ids:
        return opening_id
    if opening_id is None and len(openings) == 1:
        return openings[0].id
    raise Problem(
        "opening_required",
        detail="Choose an opening before using this committee workflow.",
    )
