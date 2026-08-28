"""Submitted applications active in ordinary committee workflows and AI."""

from sqlalchemy import Select, exists, not_, select
from sqlalchemy.orm import Session

from app.core.time import pacific_today
from app.db.models import (
    Application,
    ApplicationParticipation,
    Opening,
    OpeningOutcome,
)


def committee_applications_query() -> Select[tuple[Application]]:
    current_participation = exists(
        select(ApplicationParticipation.id)
        .join(Opening, Opening.id == ApplicationParticipation.opening_id)
        .where(
            ApplicationParticipation.application_id == Application.id,
            ApplicationParticipation.withdrawn_at.is_(None),
            Opening.published_at.is_not(None),
            Opening.move_in_date > pacific_today(),
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
        not_(selected),
        current_participation,
    )


def committee_applications(db: Session) -> list[Application]:
    return list(db.scalars(committee_applications_query().order_by(Application.id)).all())


def committee_application(db: Session, application_id: int) -> Application | None:
    return db.scalar(
        committee_applications_query().where(Application.id == application_id)
    )
