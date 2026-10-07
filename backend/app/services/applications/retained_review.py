"""Application scope for the admin retained-detail reader and its context links."""

from sqlalchemy import exists, or_, select

from app.db.models import Application, ApplicationParticipation, OpeningOutcome
from app.services.applications.retention import current_retention_clause
from app.services.openings.direct_selection import available_previous_applicants_query


def retained_review_applications_query():
    selected = exists(select(ApplicationParticipation.id).where(
        ApplicationParticipation.application_id == Application.id,
        ApplicationParticipation.outcome == OpeningOutcome.SELECTED,
    ))
    previous = available_previous_applicants_query().with_only_columns(Application.id)
    return select(Application).where(
        current_retention_clause(),
        or_(selected, Application.id.in_(previous)),
    )
