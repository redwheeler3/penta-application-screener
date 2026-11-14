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
from app.schemas.openings import OpeningCreate, OpeningCreationRequest, OpeningUpdate
from app.services.applications.retention import refresh_draft_retention_for_opening
from app.services.eligibility.rules import create_opening_rules
from app.services.openings.protection import (
    available_protection_ids,
    lock_openings,
    replace_opening_protection,
)


def opening_phase(opening: Opening, *, today: date | None = None) -> OpeningPhase:
    current_date = today or pacific_today()
    if opening.decided_at is not None:
        return OpeningPhase.ARCHIVED
    if opening.intake_mode == OpeningIntakeMode.APPLICATIONS and opening.published_at is None:
        return OpeningPhase.PREPARING
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
    creation_request_id: str | None = None,
    creation_request: dict | None = None,
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
    lock_openings(db)
    protected_ids = available_protection_ids(db, now=now)
    opening = Opening(
        creation_request_id=creation_request_id,
        creation_request=creation_request,
        **values.model_dump(include={
            "unit_size_bedrooms",
            "housing_charge_cents",
            "application_close_date",
            "move_in_date",
        }),
        application_open_date=None,
        intake_mode=OpeningIntakeMode.APPLICATIONS,
        published_at=None,
    )
    db.add(opening)
    db.flush()
    create_opening_rules(db, opening)
    replace_opening_protection(db, opening.id, protected_ids)
    return opening


def created_request(db: Session, values: OpeningCreationRequest) -> Opening | None:
    opening = db.scalar(select(Opening).where(
        Opening.creation_request_id == str(values.creation_request_id),
    ))
    if opening is not None and opening.creation_request != creation_facts(values):
        raise Problem("opening_creation_changed",
            detail="This opening creation was already saved with different facts. Reload the opening list before creating another opening.")
    return opening


def creation_facts(values: OpeningCreationRequest) -> dict:
    return values.model_dump(mode="json", exclude={"creation_request_id"})


def update_opening(db: Session, opening: Opening, values: OpeningUpdate) -> Opening:
    lock_openings(db)
    db.refresh(opening)
    if opening.intake_mode != OpeningIntakeMode.APPLICATIONS:
        raise Problem(
            "invalid_settings",
            detail="Direct-selection openings cannot be edited.",
        )
    protected_ids = available_protection_ids(db) if opening.decided_at is None else []
    if values.original.application_open_date != opening.application_open_date:
        raise Problem("stale_opening", detail="Applications opened while you were editing. Reload the saved facts.")
    if values.changes.application_open_date != opening.application_open_date:
        raise Problem("invalid_settings", detail="The application open date is set when applications open.")
    expected = values.original.model_dump()
    saved = db.execute(update(Opening).where(
        Opening.id == opening.id,
        *(getattr(Opening, field) == value for field, value in expected.items()),
    ).values(**values.changes.model_dump()).execution_options(synchronize_session=False))
    if saved.rowcount != 1:
        raise Problem("stale_opening", detail="This opening changed while you were editing. Reload its saved facts before saving again.")
    db.refresh(opening)
    if opening.decided_at is None:
        replace_opening_protection(db, opening.id, protected_ids)
    refresh_draft_retention_for_opening(db, opening.id)
    db.commit()
    db.refresh(opening)
    return opening


def publish_opening(db: Session, opening: Opening, *, now: datetime | None = None) -> None:
    """Open saved vacancy facts inside the caller's notification transaction."""
    now = now or datetime.now(UTC)
    lock_openings(db)
    db.refresh(opening)
    if opening.decided_at is not None or opening.published_at is not None:
        raise Problem("invalid_settings", detail="This opening is no longer Preparing.")
    if opening.application_close_date < pacific_today(now=now):
        raise Problem("invalid_settings", detail="Extend the application deadline before opening applications.")
    protected_ids = available_protection_ids(db, now=now)
    opening.application_open_date = pacific_today(now=now)
    opening.published_at = now
    db.flush()
    replace_opening_protection(db, opening.id, protected_ids)
    refresh_draft_retention_for_opening(db, opening.id, now=now)
