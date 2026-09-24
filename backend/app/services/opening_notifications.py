"""Release closeout email only after every opening an applicant entered is final."""

from collections.abc import Iterator
from dataclasses import dataclass
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
from app.services.email_delivery import deliver_email
from app.services.email_sender import EmailSender
from app.services.openings import opening_phase
from app.services.transactional_email import unsuccessful_application_email


@dataclass(frozen=True)
class OutcomeNoticeProgress:
    processed: int
    total: int
    sent: int


@dataclass(frozen=True)
class _OutcomeNotice:
    application: Application
    participations: tuple[ApplicationParticipation, ...]
    opening_ids: tuple[int, ...]
    labels: tuple[str, ...]


def send_due_unsuccessful_notices(
    db: Session, sender: EmailSender, *, now: datetime | None = None
) -> int:
    """Send each newly eligible household one notice, safely repeatable."""
    sent = 0
    for progress in stream_due_unsuccessful_notices(db, sender, now=now):
        sent = progress.sent
    return sent


def stream_due_unsuccessful_notices(
    db: Session,
    sender: EmailSender,
    *,
    application_ids: set[int] | None = None,
    now: datetime | None = None,
) -> Iterator[OutcomeNoticeProgress]:
    """Send due notices sequentially and expose provider-backed progress."""
    now = now or datetime.now(UTC)
    notices = _due_unsuccessful_notices(db, application_ids=application_ids)
    sent = 0
    yield OutcomeNoticeProgress(processed=0, total=len(notices), sent=0)
    for processed, notice in enumerate(notices, start=1):
        delivered = deliver_email(
            db,
            sender,
            unsuccessful_application_email(
                application_id=notice.application.id,
                email=notice.application.primary_email,
                opening_labels=list(notice.labels),
            ),
            recipient_kind=PasswordlessIdentityKind.APPLICANT,
            application_id=notice.application.id,
            idempotency_key=(
                f"application-unsuccessful:{notice.application.id}:"
                + ",".join(str(opening_id) for opening_id in notice.opening_ids)
            ),
            retry_intent={
                "type": "application_unsuccessful",
                "opening_labels": list(notice.labels),
            },
            now=now,
        )
        if delivered:
            for participation in notice.participations:
                participation.unsuccessful_notified_at = now
            db.commit()
            sent += 1
        yield OutcomeNoticeProgress(
            processed=processed,
            total=len(notices),
            sent=sent,
        )


def _due_unsuccessful_notices(
    db: Session, *, application_ids: set[int] | None = None
) -> list[_OutcomeNotice]:
    notices: list[_OutcomeNotice] = []
    statement = select(Application).where(
        Application.submitted_at.is_not(None),
        Application.withdrawn_at.is_(None),
    )
    if application_ids is not None:
        statement = statement.where(Application.id.in_(application_ids))
    applications = db.scalars(statement).all()
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
        opening_ids = tuple(
            sorted(participation.opening_id for participation in unnotified)
        )
        labels = [
            _opening_label(opening)
            for participation, opening in participations
            if participation.opening_id in opening_ids
        ]
        notices.append(
            _OutcomeNotice(
                application=application,
                participations=tuple(unnotified),
                opening_ids=opening_ids,
                labels=tuple(labels),
            )
        )
    return notices


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
    move_in = (
        f"{opening.move_in_date.strftime('%B')} {opening.move_in_date.day}, "
        f"{opening.move_in_date.year}"
    )
    return f"the {opening.unit_size_bedrooms}-bedroom home ({move_in} move-in)"
