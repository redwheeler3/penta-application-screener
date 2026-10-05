"""Release closeout email only after every opening an applicant entered is final."""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import exists, or_, select, update
from sqlalchemy.orm import Session

from app.db.models import (
    Application,
    ApplicationParticipation,
    EmailDelivery,
    EmailDeliveryState,
    Opening,
    OpeningOutcome,
    OpeningPhase,
    PasswordlessIdentityKind,
)
from app.services.applications.locking import lock_application
from app.services.applications.retention import (
    current_retention_clause,
    retention_is_current,
)
from app.services.email.delivery import queue_email
from app.services.email.retry_intents import UnsuccessfulApplicationRetryIntent
from app.services.email.templates import unsuccessful_application_email
from app.services.openings.catalog import opening_phase


@dataclass(frozen=True)
class _OutcomeNotice:
    application: Application
    opening_ids: tuple[int, ...]
    labels: tuple[str, ...]


def queue_due_unsuccessful_notices(
    db: Session, *, application_ids: set[int] | None = None,
    now: datetime | None = None, commit: bool = True,
) -> int:
    """Stage due closeout intents; decision callers include them in their own transaction."""
    now = now or datetime.now(UTC)
    db.flush()
    active = (ApplicationParticipation.application_id == Application.id,
              ApplicationParticipation.withdrawn_at.is_(None))
    unnotified = exists(select(ApplicationParticipation.id).where(
        *active, ApplicationParticipation.unsuccessful_notified_at.is_(None)))
    unfinished = exists(select(ApplicationParticipation.id).join(Opening).where(
        *active, or_(ApplicationParticipation.outcome.is_(None),
                     ApplicationParticipation.outcome != OpeningOutcome.UNSUCCESSFUL,
                     Opening.decided_at.is_(None))))
    query = select(Application.id).where(Application.submitted_at.is_not(None),
        Application.withdrawn_at.is_(None), current_retention_clause(now=now), unnotified, ~unfinished)
    if application_ids is not None:
        query = query.where(Application.id.in_(application_ids))
    ids = list(db.scalars(query))
    queued = 0
    captured = {notice.application.id: notice for notice in _due_unsuccessful_notices(db, application_ids=set(ids), now=now)} if not commit else None
    for application_id in ids:
        if commit and lock_application(db, application_id) is None:
            db.commit()
            continue
        notices = ([captured[application_id]] if application_id in captured else []) if captured is not None else _due_unsuccessful_notices(db, application_ids={application_id}, now=now)
        for notice in notices:
            intent = UnsuccessfulApplicationRetryIntent(type="application_unsuccessful", opening_labels=list(notice.labels))
            delivery = queue_email(
                db, unsuccessful_application_email(application_id=application_id,
                    email=notice.application.primary_email, opening_labels=list(notice.labels)),
                recipient_kind=PasswordlessIdentityKind.APPLICANT, application_id=application_id,
                idempotency_key=f"application-unsuccessful:{application_id}:" + ",".join(str(id) for id in notice.opening_ids),
                retry_intent=intent,
            )
            if delivery.state == EmailDeliveryState.ACCEPTED:
                record_unsuccessful_delivery(db, delivery)
            else:
                if delivery.state == EmailDeliveryState.FAILED:
                    # Reconsider failures only after checking the household's current state.
                    delivery.state = EmailDeliveryState.QUEUED
                    delivery.retry_intent = intent
                    delivery.last_attempt_at = None
                    delivery.last_error_code = None
                    delivery.quota_blocked = False
                queued += 1
        if commit:
            db.commit()
    return queued


def record_unsuccessful_delivery(db: Session, delivery: EmailDelivery) -> None:
    """Record acceptance with the same transaction as the delivery ledger update."""
    prefix = f"application-unsuccessful:{delivery.application_id}:"
    key = delivery.idempotency_key or ""
    if not key.startswith(prefix):
        raise ValueError("Invalid unsuccessful-notice identity")
    opening_ids = [int(value) for value in key.removeprefix(prefix).split(",")]
    db.execute(update(ApplicationParticipation).where(
        ApplicationParticipation.application_id == delivery.application_id,
        ApplicationParticipation.opening_id.in_(opening_ids),
        ApplicationParticipation.outcome == OpeningOutcome.UNSUCCESSFUL,
        ApplicationParticipation.unsuccessful_notified_at.is_(None),
    ).values(unsuccessful_notified_at=delivery.last_attempt_at))


def unsuccessful_notice_is_available(db: Session, application: Application, *, now: datetime | None = None) -> bool:
    return retention_is_current(application, now=now) and application.withdrawn_at is None and _is_unsuccessful_and_final(_active_participations(db, application.id))


def _due_unsuccessful_notices(
    db: Session, *, application_ids: set[int] | None = None, now: datetime | None = None
) -> list[_OutcomeNotice]:
    notices: list[_OutcomeNotice] = []
    statement = select(Application).where(
        Application.submitted_at.is_not(None),
        Application.withdrawn_at.is_(None),
        current_retention_clause(now=now),
    ).execution_options(populate_existing=True)
    if application_ids is not None:
        statement = statement.where(Application.id.in_(application_ids))
    applications = db.scalars(statement).all()
    if not applications:
        return []
    by_application = {application.id: [] for application in applications}
    rows = db.execute(select(ApplicationParticipation, Opening).join(Opening, Opening.id == ApplicationParticipation.opening_id)
        .where(ApplicationParticipation.application_id.in_(by_application), ApplicationParticipation.withdrawn_at.is_(None))
        .order_by(Opening.move_in_date, Opening.id).execution_options(populate_existing=True))
    for participation, opening in rows:
        by_application[participation.application_id].append((participation, opening))
    for application in applications:
        participations = by_application[application.id]
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
