"""Private applicant drafts that become applications only after email-link access."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.text import normalize_email
from app.core.time import as_utc, pacific_today
from app.db.models import (
    ApplicantDraft,
    ApplicantDraftIntent,
    Application,
    EmailDelivery,
    EmailDeliveryState,
    MagicLinkPurpose,
    MagicLinkToken,
)
from app.schemas.intake import WorkingApplicationAnswers
from app.services.retention import retention_due_for_opening_ids
from app.services.token_credentials import new_token, token_hash


@dataclass(frozen=True)
class SavedApplicantDraft:
    token: str
    record: ApplicantDraft


def save_pending_draft(
    db: Session,
    *,
    answers: WorkingApplicationAnswers,
    opening_ids: list[int],
    retention_opening_ids: list[int] | None = None,
    intent: ApplicantDraftIntent,
    draft_token: str | None = None,
    now: datetime | None = None,
) -> SavedApplicantDraft:
    now = now or datetime.now(UTC)
    email = normalize_email(str(answers.applicant.email))
    record = pending_draft_for_token(db, draft_token) if draft_token else None
    if record is not None and record.email != email:
        record = None

    retention_due_on = retention_due_for_opening_ids(
        db, retention_opening_ids if retention_opening_ids is not None else opening_ids
    )
    if retention_due_on is None:
        raise ValueError("A pending draft must belong to at least one opening.")

    raw_token = draft_token if record is not None else new_token()
    if record is None:
        application = db.scalar(
            select(Application).where(
                Application.primary_email == email,
                Application.deleted_at.is_(None),
            )
        )
        record = ApplicantDraft(
            email=email,
            intent=intent,
            application_id=application.id if application is not None else None,
            draft_token_hash=token_hash(raw_token),
            created_at=now,
            saved_at=now,
            retention_due_on=retention_due_on,
        )
        db.add(record)
    record.intent = intent
    record.working_answers = answers.model_dump(mode="json")
    record.working_opening_ids = list(opening_ids)
    record.saved_at = now
    record.retention_due_on = retention_due_on
    record.resolved_at = None
    record.revoked_at = None
    db.flush()
    return SavedApplicantDraft(token=raw_token, record=record)


def save_collision_copy(
    db: Session,
    *,
    application: Application,
    answers: WorkingApplicationAnswers,
    opening_ids: list[int],
    now: datetime | None = None,
) -> ApplicantDraft:
    """Preserve the latest guest copy without invalidating an email already in flight."""
    now = now or datetime.now(UTC)
    record = latest_pending_draft_for_email(db, application.primary_email, now=now)
    retention_due_on = retention_due_for_opening_ids(db, opening_ids)
    if retention_due_on is None:
        raise ValueError("A pending copy must belong to at least one opening.")
    if record is None or record.application_id not in {None, application.id}:
        record = ApplicantDraft(
            email=application.primary_email,
            intent=ApplicantDraftIntent.SUBMIT,
            application_id=application.id,
            draft_token_hash=token_hash(new_token()),
            created_at=now,
            saved_at=now,
            retention_due_on=retention_due_on,
        )
        db.add(record)
    record.application_id = application.id
    record.intent = ApplicantDraftIntent.SUBMIT
    record.working_answers = answers.model_dump(mode="json")
    record.working_opening_ids = list(opening_ids)
    record.saved_at = now
    record.retention_due_on = retention_due_on
    record.resolved_at = None
    record.revoked_at = None
    db.flush()
    return record


def pending_draft_for_token(db: Session, raw_token: str) -> ApplicantDraft | None:
    record = db.scalar(
        select(ApplicantDraft).where(ApplicantDraft.draft_token_hash == token_hash(raw_token))
    )
    if record is None or not draft_is_available(record):
        return None
    return record


def latest_pending_draft_for_email(
    db: Session,
    email: str,
    *,
    now: datetime | None = None,
) -> ApplicantDraft | None:
    """Return the newest usable Save-and-return-later draft for an address."""
    now = now or datetime.now(UTC)
    return db.scalar(
        select(ApplicantDraft)
        .where(
            ApplicantDraft.email == normalize_email(email),
            ApplicantDraft.revoked_at.is_(None),
            ApplicantDraft.resolved_at.is_(None),
            ApplicantDraft.retention_due_on > pacific_today(now=now),
        )
        .order_by(ApplicantDraft.saved_at.desc())
        .limit(1)
    )


def revoke_other_pending_drafts(
    db: Session,
    record: ApplicantDraft,
    *,
    now: datetime | None = None,
) -> None:
    """Make one pending browser copy the only copy that can still be claimed."""
    now = now or datetime.now(UTC)
    for older in db.scalars(
        select(ApplicantDraft).where(
            ApplicantDraft.email == record.email,
            ApplicantDraft.id != record.id,
            ApplicantDraft.resolved_at.is_(None),
            ApplicantDraft.revoked_at.is_(None),
        )
    ):
        older.revoked_at = now


def draft_is_available(record: ApplicantDraft, *, now: datetime | None = None) -> bool:
    now = now or datetime.now(UTC)
    return (
        record.revoked_at is None
        and record.resolved_at is None
        and record.retention_due_on > pacific_today(now=now)
    )


def applicant_email_request_allowed(
    db: Session,
    email: str,
    *,
    now: datetime | None = None,
) -> bool:
    """Rate-limit applicant access mail by address, not by disposable draft identity."""
    now = now or datetime.now(UTC)
    settings = get_settings()
    filters = (
        MagicLinkToken.email == normalize_email(email),
        MagicLinkToken.purpose == MagicLinkPurpose.APPLICANT_ACCESS,
    )
    delivered_or_unrecorded = ~exists(
        select(EmailDelivery.id).where(
            EmailDelivery.magic_link_token_id == MagicLinkToken.id,
            EmailDelivery.state == EmailDeliveryState.FAILED,
        )
    )
    latest = db.scalar(
        select(func.max(MagicLinkToken.created_at)).where(
            *filters,
            delivered_or_unrecorded,
            MagicLinkToken.consumed_at.is_(None),
            MagicLinkToken.revoked_at.is_(None),
        )
    )
    if latest is not None and as_utc(latest) > now - timedelta(
        seconds=settings.magic_link_coalesce_seconds
    ):
        return False
    count = db.scalar(
        select(func.count())
        .select_from(MagicLinkToken)
        .where(
            *filters,
            delivered_or_unrecorded,
            MagicLinkToken.created_at
            > now - timedelta(minutes=settings.magic_link_rate_window_minutes),
        )
    )
    return int(count or 0) < settings.magic_link_request_limit
