"""Submitted applications visible to ordinary committee workflows and AI."""

from sqlalchemy import Select, exists, not_, or_, select
from sqlalchemy.orm import Session

from app.db.models import (
    Application,
    ApplicationParticipation,
    Opening,
    OpeningOutcome,
)


def committee_applications_query() -> Select[tuple[Application]]:
    published_opening_exists = exists(
        select(Opening.id).where(Opening.published_at.is_not(None))
    )
    active_participation = exists(
        select(ApplicationParticipation.id)
        .where(
            ApplicationParticipation.application_id == Application.id,
            ApplicationParticipation.withdrawn_at.is_(None),
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
        Application.deleted_at.is_(None),
        not_(selected),
        # Retained externally collected applications remain available until the first
        # built-in opening is published. From then on, participation owns scope; an
        # archived unsuccessful application remains live until its physical purge.
        or_(not_(published_opening_exists), active_participation),
    )


def committee_applications(db: Session) -> list[Application]:
    return list(db.scalars(committee_applications_query().order_by(Application.id)).all())


def committee_application(db: Session, application_id: int) -> Application | None:
    return db.scalar(
        committee_applications_query().where(Application.id == application_id)
    )
