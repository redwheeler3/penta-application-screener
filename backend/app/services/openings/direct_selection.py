"""Fill an opening from retained previous applicants without launching intake."""

from datetime import UTC, datetime

from sqlalchemy import Select, exists, not_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.problems import Problem
from app.db.models import (
    Application,
    ApplicationParticipation,
    Opening,
    OpeningIntakeMode,
    OpeningOutcome,
    User,
)
from app.services.applications.locking import lock_application
from app.services.applications.retention import (
    current_retention_clause,
    refresh_application_retention,
)
from app.services.applications.scope import ApplicantIdentity
from app.services.applications.selected import revoke_selected_applicant_access
from app.services.auth.authority import require_admin_write


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
        Application.retention_due_on.is_not(None),
        current_retention_clause(),
        participated,
        not_(selected),
    )


def search_previous_applicants(
    db: Session, query: str, *, limit: int = 25
) -> list[ApplicantIdentity]:
    if limit < 1:
        return []
    terms = query.casefold().split()
    statement = available_previous_applicants_query().with_only_columns(
        Application.id, Application.applicant_name, Application.primary_email,
    ).order_by(Application.applicant_name, Application.id)
    matches = []
    for identity, name, email in db.execute(statement):
        folded_name, folded_email = (name or "").casefold(), email.casefold()
        if all(term in folded_name or term in folded_email for term in terms):
            matches.append(ApplicantIdentity(identity, name, email))
            if len(matches) == limit:
                break
    return matches


def available_previous_applicant(
    db: Session, application_id: int
) -> Application | None:
    return db.scalar(
        available_previous_applicants_query().where(Application.id == application_id)
    )


def select_previous_applicant(
    db: Session,
    opening: Opening,
    application_id: int,
    *,
    decided_by: User,
    now: datetime | None = None,
) -> Opening:
    now = now or datetime.now(UTC)
    lock_application(db, application_id)
    decided_by = require_admin_write(db, decided_by.id)
    application = available_previous_applicant(db, application_id)
    if application is None:
        raise Problem(
            "invalid_settings",
            detail="Choose an available retained applicant.",
        )

    db.refresh(opening)
    if opening.published_at is not None or opening.decided_at is not None:
        raise Problem("invalid_settings", detail="Choose a previous applicant only while this opening is Preparing.")
    opening.intake_mode = OpeningIntakeMode.DIRECT_SELECTION
    opening.decided_at = now
    opening.decided_by_user_id = decided_by.id
    try:
        db.add(
            ApplicationParticipation(
                application_id=application.id,
                opening_id=opening.id,
                applied_at=now,
                outcome=OpeningOutcome.SELECTED,
            )
        )
        db.flush()
        refresh_application_retention(db, application)
        revoke_selected_applicant_access(db, application.id, now=now)
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise Problem(
            "invalid_settings",
            detail="That applicant was selected elsewhere. Search again.",
        ) from error
    db.refresh(opening)
    return opening
