"""The one application scope visible to committee workflows and AI processing."""

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.db.models import Application


def committee_applications_query() -> Select[tuple[Application]]:
    return select(Application).where(
        Application.submitted_at.is_not(None),
        Application.deleted_at.is_(None),
    )


def committee_applications(db: Session) -> list[Application]:
    return list(db.scalars(committee_applications_query().order_by(Application.id)).all())


def committee_application(db: Session, application_id: int) -> Application | None:
    return db.scalar(
        committee_applications_query().where(Application.id == application_id)
    )
