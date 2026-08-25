"""The current-opening application scope visible to committee workflows and AI."""

from sqlalchemy import Select, exists, not_, or_, select
from sqlalchemy.orm import Session

from app.core.time import pacific_today
from app.db.models import Application, ApplicationParticipation, Opening


def committee_applications_query() -> Select[tuple[Application]]:
    published_opening_exists = exists(
        select(Opening.id).where(Opening.published_at.is_not(None))
    )
    current_participation = exists(
        select(ApplicationParticipation.id)
        .join(Opening, Opening.id == ApplicationParticipation.opening_id)
        .where(
            ApplicationParticipation.application_id == Application.id,
            ApplicationParticipation.withdrawn_at.is_(None),
            Opening.move_in_date > pacific_today(),
        )
    )
    return select(Application).where(
        Application.submitted_at.is_not(None),
        Application.deleted_at.is_(None),
        # Retained externally collected applications remain available until the first
        # built-in opening is published. From then on, current participation owns scope.
        or_(not_(published_opening_exists), current_participation),
    )


def committee_applications(db: Session) -> list[Application]:
    return list(db.scalars(committee_applications_query().order_by(Application.id)).all())


def committee_application(db: Session, application_id: int) -> Application | None:
    return db.scalar(
        committee_applications_query().where(Application.id == application_id)
    )
