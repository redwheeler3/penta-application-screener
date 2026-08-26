"""Opening publication and date-derived lifecycle rules."""

from datetime import UTC, date, datetime

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.api.problems import Problem
from app.core.time import pacific_today
from app.db.models import Application, ApplicationParticipation, Opening, OpeningPhase
from app.schemas.openings import OpeningWrite
from app.services.retention import (
    refresh_application_retention,
    refresh_draft_retention_for_opening,
)


def opening_phase(opening: Opening, *, today: date | None = None) -> OpeningPhase:
    if opening.published_at is None:
        return OpeningPhase.DRAFT
    current_date = today or pacific_today()
    if current_date >= opening.move_in_date:
        return OpeningPhase.ARCHIVED
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
            .where(Opening.published_at.is_not(None))
            .order_by(Opening.move_in_date.desc(), Opening.id.desc())
        )
    )


def create_opening(db: Session, values: OpeningWrite) -> Opening:
    opening = Opening(**values.model_dump())
    db.add(opening)
    db.commit()
    db.refresh(opening)
    return opening


def update_opening(db: Session, opening: Opening, values: OpeningWrite) -> Opening:
    for field, value in values.model_dump().items():
        setattr(opening, field, value)
    db.flush()
    _refresh_participant_retention(db, opening.id)
    refresh_draft_retention_for_opening(db, opening.id)
    db.commit()
    db.refresh(opening)
    return opening


def _refresh_participant_retention(db: Session, opening_id: int) -> None:
    application_ids = list(
        db.scalars(
            select(ApplicationParticipation.application_id).where(
                ApplicationParticipation.opening_id == opening_id
            )
        )
    )
    for application_id in set(application_ids):
        application = db.get(Application, application_id)
        if application is not None:
            refresh_application_retention(db, application)


def publish_opening(
    db: Session,
    opening: Opening,
    *,
    now: datetime | None = None,
) -> Opening:
    now = now or datetime.now(UTC)
    if opening.published_at is not None:
        return opening
    if opening.move_in_date <= pacific_today(now=now):
        raise Problem(
            "invalid_settings",
            detail="The move-in date must be in the future before publishing an opening.",
        )
    opening.published_at = now
    db.commit()
    db.refresh(opening)
    return opening
