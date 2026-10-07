"""Opening publication and date-derived lifecycle rules."""

from datetime import UTC, date, datetime

from sqlalchemy import and_, func, select, update
from sqlalchemy.orm import Session

from app.core.problems import Problem
from app.core.time import pacific_today
from app.db.models import (
    ApplicationParticipation,
    Opening,
    OpeningIntakeMode,
    OpeningPhase,
)
from app.schemas.openings import OpeningCreate, OpeningCreateConfirmation, OpeningUpdate
from app.services.applications.retention import refresh_draft_retention_for_opening
from app.services.eligibility.rules import create_opening_rules


def opening_phase(opening: Opening, *, today: date | None = None) -> OpeningPhase:
    current_date = today or pacific_today()
    if opening.decided_at is not None:
        return OpeningPhase.ARCHIVED
    if opening.intake_mode == OpeningIntakeMode.DIRECT_SELECTION:
        return OpeningPhase.CLOSED
    if opening.application_open_date is None or opening.application_close_date is None:
        raise ValueError("Application openings require open and close dates.")
    if current_date < opening.application_open_date:
        return OpeningPhase.UPCOMING
    if current_date <= opening.application_close_date:
        return OpeningPhase.OPEN
    return OpeningPhase.CLOSED


def list_openings(db: Session) -> list[tuple[Opening, int]]:
    return list(
        db.execute(
            select(Opening, func.count(ApplicationParticipation.id))
            .outerjoin(
                ApplicationParticipation,
                and_(
                    ApplicationParticipation.opening_id == Opening.id,
                    ApplicationParticipation.withdrawn_at.is_(None),
                ),
            )
            .group_by(Opening.id)
            .order_by(Opening.move_in_date.desc(), Opening.id.desc())
        ).all()
    )


def published_openings(db: Session) -> list[Opening]:
    return list(
        db.scalars(
            select(Opening)
            .where(
                Opening.published_at.is_not(None),
                Opening.intake_mode == OpeningIntakeMode.APPLICATIONS,
            )
            .order_by(Opening.move_in_date.desc(), Opening.id.desc())
        )
    )


def create_opening(
    db: Session,
    values: OpeningCreate,
    *,
    now: datetime | None = None,
    publication_request_id: str | None = None,
    publication_request: dict | None = None,
) -> Opening:
    now = now or datetime.now(UTC)
    today = pacific_today(now=now)
    if values.application_close_date < today:
        raise Problem(
            "invalid_settings",
            detail="The application close date cannot be in the past.",
        )
    if values.move_in_date <= today:
        raise Problem(
            "invalid_settings",
            detail="The move-in date must be in the future.",
        )
    opening = Opening(
        publication_request_id=publication_request_id,
        publication_request=publication_request,
        **values.model_dump(include={
            "unit_size_bedrooms",
            "housing_charge_cents",
            "application_close_date",
            "move_in_date",
        }),
        application_open_date=today,
        intake_mode=OpeningIntakeMode.APPLICATIONS,
        published_at=now,
    )
    db.add(opening)
    db.flush()
    create_opening_rules(db, opening)
    refresh_draft_retention_for_opening(db, opening.id, now=now)
    return opening


def published_request(db: Session, values: OpeningCreateConfirmation) -> Opening | None:
    opening = db.scalar(select(Opening).where(
        Opening.publication_request_id == str(values.publication_request_id),
    ))
    if opening is not None and opening.publication_request != publication_facts(values):
        raise Problem("opening_publication_changed",
            detail="This publication was already saved with different facts. Reload the opening list before creating another opening.")
    return opening


def publication_facts(values: OpeningCreateConfirmation) -> dict:
    return values.model_dump(mode="json", exclude={"publication_request_id"})


def update_opening(db: Session, opening: Opening, values: OpeningUpdate) -> Opening:
    if opening.intake_mode != OpeningIntakeMode.APPLICATIONS:
        raise Problem(
            "invalid_settings",
            detail="Direct-selection openings cannot be edited.",
        )
    expected = values.original.model_dump()
    saved = db.execute(update(Opening).where(
        Opening.id == opening.id,
        *(getattr(Opening, field) == value for field, value in expected.items()),
    ).values(**values.changes.model_dump()).execution_options(synchronize_session=False))
    if saved.rowcount != 1:
        raise Problem("stale_opening", detail="This opening changed while you were editing. Reload its saved facts before saving again.")
    db.refresh(opening)
    refresh_draft_retention_for_opening(db, opening.id)
    db.commit()
    db.refresh(opening)
    return opening
