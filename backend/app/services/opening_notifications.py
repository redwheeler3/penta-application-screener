"""Release closeout email only after every opening an applicant entered is final."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    Application,
    ApplicationParticipation,
    Opening,
    OpeningOutcome,
    OpeningPhase,
    PasswordlessIdentityKind,
)
from app.services.auth_email import unsuccessful_application_email
from app.services.email_delivery import deliver_email
from app.services.email_sender import EmailSender
from app.services.openings import opening_phase


def send_due_unsuccessful_notices(
    db: Session, sender: EmailSender, *, now: datetime | None = None
) -> int:
    """Send each newly eligible household one notice, safely repeatable."""
    now = now or datetime.now(UTC)
    sent = 0
    applications = db.scalars(
        select(Application).where(
            Application.submitted_at.is_not(None),
            Application.deleted_at.is_(None),
        )
    ).all()
    for application in applications:
        participations = _active_participations(db, application.id)
        if not _is_unsuccessful_and_final(participations):
            continue
        unnotified = [
            participation
            for participation, _ in participations
            if participation.unsuccessful_notified_at is None
        ]
        if not unnotified:
            continue
        opening_ids = sorted(participation.opening_id for participation in unnotified)
        labels = [
            _opening_label(opening)
            for participation, opening in participations
            if participation.opening_id in opening_ids
        ]
        delivered = deliver_email(
            db,
            sender,
            unsuccessful_application_email(
                application_id=application.id,
                email=application.primary_email,
                opening_labels=labels,
            ),
            recipient_kind=PasswordlessIdentityKind.APPLICANT,
            application_id=application.id,
            idempotency_key=(
                f"application-unsuccessful:{application.id}:"
                + ",".join(str(opening_id) for opening_id in opening_ids)
            ),
            retry_intent={
                "type": "application_unsuccessful",
                "opening_labels": labels,
            },
            now=now,
        )
        if not delivered:
            continue
        for participation in unnotified:
            participation.unsuccessful_notified_at = now
        db.commit()
        sent += 1
    return sent


def _active_participations(
    db: Session, application_id: int
) -> list[tuple[ApplicationParticipation, Opening]]:
    return list(
        db.execute(
            select(ApplicationParticipation, Opening)
            .join(Opening, Opening.id == ApplicationParticipation.opening_id)
            .where(
                ApplicationParticipation.application_id == application_id,
                ApplicationParticipation.withdrawn_at.is_(None),
            )
            .order_by(Opening.move_in_date, Opening.id)
        ).all()
    )


def _is_unsuccessful_and_final(
    participations: list[tuple[ApplicationParticipation, Opening]],
) -> bool:
    return bool(participations) and all(
        participation.outcome == OpeningOutcome.UNSUCCESSFUL
        and opening_phase(opening) == OpeningPhase.ARCHIVED
        for participation, opening in participations
    )


def _opening_label(opening: Opening) -> str:
    date_label = opening.move_in_date.strftime("%B ") + str(opening.move_in_date.day)
    date_label += opening.move_in_date.strftime(", %Y")
    return f"the {opening.unit_size_bedrooms}-bedroom opening ({date_label} move-in)"
