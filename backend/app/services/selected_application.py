"""Selected-applicant access lock for the retained membership record."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    ApplicationParticipation,
    OpeningOutcome,
    PasswordlessIdentityKind,
)
from app.services.email_delivery import cancel_queued_application_emails
from app.services.passwordless_auth import (
    revoke_identity_magic_links,
    revoke_identity_sessions,
)


def selected_opening_id(db: Session, application_id: int) -> int | None:
    return db.scalar(
        select(ApplicationParticipation.opening_id).where(
            ApplicationParticipation.application_id == application_id,
            ApplicationParticipation.outcome == OpeningOutcome.SELECTED,
        )
    )


def application_is_selected(db: Session, application_id: int) -> bool:
    return selected_opening_id(db, application_id) is not None


def revoke_selected_applicant_access(
    db: Session,
    application_id: int,
    *,
    now: datetime | None = None,
) -> None:
    """End every applicant credential when the committee selects the household."""
    now = now or datetime.now(UTC)
    cancel_queued_application_emails(
        db,
        application_id,
        error_code="ApplicationSelected",
    )
    revoke_identity_sessions(
        db,
        identity_kind=PasswordlessIdentityKind.APPLICANT,
        application_id=application_id,
        now=now,
    )
    revoke_identity_magic_links(
        db,
        identity_kind=PasswordlessIdentityKind.APPLICANT,
        application_id=application_id,
        now=now,
    )
