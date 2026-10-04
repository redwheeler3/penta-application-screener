"""Completely remove aggregates whose retention period has ended."""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete as sql_delete
from sqlalchemy import or_, select, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from app.core.time import pacific_today
from app.db.models import (
    ApplicantDraft,
    Application,
    ApplicationParticipation,
    BrowserSession,
    EmailDelivery,
    Feedback,
    MagicLinkToken,
    OpeningOutcome,
    PasswordlessIdentityKind,
    RetentionDeletion,
)
from app.services.applications.locking import lock_application


@dataclass(frozen=True)
class PurgeSummary:
    applications_purged: int = 0
    drafts_purged: int = 0


def purge_due_applicant_data(db: Session, *, now: datetime | None = None) -> PurgeSummary:
    """Purge all records due on the Pacific date, retaining only deletion facts."""
    now = now or datetime.now(UTC)
    today = pacific_today(now=now)
    applications_purged = 0
    drafts_purged = 0

    application_ids = db.scalars(
        select(Application.id)
        .where(
            Application.retention_due_on.is_not(None),
            Application.retention_due_on <= today,
        )
        .order_by(Application.id)
    ).all()
    for application_id in application_ids:
        application = lock_application(db, application_id)
        if application is None or application.retention_due_on is None or application.retention_due_on > today:
            db.commit()
            continue
        due_on = application.retention_due_on
        retention_rule = _application_retention_rule(db, application.id)
        _record_deletion(
            db,
            record_kind="application",
            record_id=application.id,
            retention_rule=retention_rule,
            due_on=due_on,
            now=now,
        )
        db.execute(
            update(Feedback)
            .where(Feedback.applicant_id == application.id)
            .values(applicant_id=None)
        )
        db.delete(application)
        db.commit()
        applications_purged += 1

    draft_due = or_(
        ApplicantDraft.resolved_at.is_not(None),
        ApplicantDraft.revoked_at.is_not(None),
        ApplicantDraft.expires_on <= today,
    )
    draft_ids = db.scalars(
        select(ApplicantDraft.id)
        .where(
            draft_due,
        )
        .order_by(ApplicantDraft.id)
    ).all()
    for draft_id in draft_ids:
        # Recheck actionability under the writer lock: an opening extension or
        # a guest save may have renewed the draft after the sweep selected its ID.
        claimed = db.execute(
            update(ApplicantDraft)
            .where(ApplicantDraft.id == draft_id, draft_due)
            .values(saved_at=ApplicantDraft.saved_at)
            .execution_options(synchronize_session=False)
        )
        if claimed.rowcount != 1:
            db.commit()
            continue
        draft = db.get(ApplicantDraft, draft_id, populate_existing=True)
        purge_draft(db, draft, now=now, retention_rule="draft_actionability")
        db.commit()
        drafts_purged += 1

    return PurgeSummary(
        applications_purged=applications_purged,
        drafts_purged=drafts_purged,
    )


def _application_retention_rule(db: Session, application_id: int) -> str:
    selected = db.scalar(
        select(ApplicationParticipation.id).where(
            ApplicationParticipation.application_id == application_id,
            ApplicationParticipation.outcome == OpeningOutcome.SELECTED,
        )
    )
    return "selected_seven_years" if selected is not None else "one_year"


def _record_deletion(
    db: Session,
    *,
    record_kind: str,
    record_id: int,
    retention_rule: str,
    due_on,
    now: datetime,
) -> None:
    # The latest deletion bound covers older snapshot generations of an identifier.
    values = {"retention_rule": retention_rule, "due_on": due_on, "deleted_at": now}
    db.execute(insert(RetentionDeletion).values(record_kind=record_kind, record_id=record_id, **values)
        .on_conflict_do_update(index_elements=[RetentionDeletion.record_kind, RetentionDeletion.record_id],
            set_=values, where=RetentionDeletion.deleted_at <= now))


def purge_draft(db: Session, draft: ApplicantDraft, *, now: datetime, retention_rule: str) -> None:
    """Remove one temporary copy, retaining its deletion fact in the caller's transaction."""
    _record_deletion(db, record_kind="applicant_draft", record_id=draft.id,
        retention_rule=retention_rule, due_on=min(draft.expires_on, pacific_today(now=now)), now=now)
    db.execute(update(BrowserSession).where(BrowserSession.reconciliation_draft_id == draft.id)
        .values(reconciliation_draft_id=None).execution_options(synchronize_session=False))
    db.delete(draft)


def purge_never_submitted_application(db: Session, application: Application) -> None:
    """Physically remove a draft-only application and its access records."""
    _record_deletion(db, record_kind="application", record_id=application.id,
        retention_rule="explicit_application_delete", due_on=pacific_today(), now=datetime.now(UTC))
    draft_ids = select(ApplicantDraft.id).where(ApplicantDraft.application_id == application.id)
    link_ids = select(MagicLinkToken.id).where(
        or_(
            MagicLinkToken.application_id == application.id,
            MagicLinkToken.applicant_draft_id.in_(draft_ids),
        )
    )
    db.execute(
        sql_delete(EmailDelivery).where(
            or_(
                EmailDelivery.application_id == application.id,
                EmailDelivery.applicant_draft_id.in_(draft_ids),
                EmailDelivery.magic_link_token_id.in_(link_ids),
            )
        )
    )
    db.execute(sql_delete(MagicLinkToken).where(MagicLinkToken.id.in_(link_ids)))
    db.execute(sql_delete(ApplicantDraft).where(ApplicantDraft.id.in_(draft_ids)))
    db.execute(
        sql_delete(BrowserSession).where(
            BrowserSession.identity_kind == PasswordlessIdentityKind.APPLICANT,
            BrowserSession.application_id == application.id,
        )
    )
    db.delete(application)
