"""Completely remove aggregates whose retention period has ended."""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import or_, select, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from app.core.time import pacific_today
from app.db.models import (
    ApplicantDraft,
    Application,
    ApplicationParticipation,
    BrowserSession,
    Feedback,
    OpeningOutcome,
    RetentionDeletion,
)
from app.services.applications.locking import lock_application
from app.services.applications.result_retention import (
    application_result_ids,
    prune_unowned_results,
)


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
        application = db.get(Application, application_id)
        if application is not None and purge_expired_application(db, application, now=now):
            applications_purged += 1
        db.commit()

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


def purge_expired_application(db: Session, application: Application, *, now: datetime) -> bool:
    """Remove one expired identity under its writer lock in the caller's transaction."""
    application = lock_application(db, application.id)
    if application is None or application.retention_due_on is None or application.retention_due_on > pacific_today(now=now):
        return False
    _record_deletion(db, record_kind="application", record_id=application.id,
                     retention_rule=_application_retention_rule(db, application),
                     due_on=application.retention_due_on, now=now)
    erase_application(db, application, now=now)
    return True


def _application_retention_rule(db: Session, application: Application) -> str:
    if application.submitted_at is None:
        return "draft_actionability"
    selected = db.scalar(
        select(ApplicationParticipation.id).where(
            ApplicationParticipation.application_id == application.id,
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
    erase_draft(db, draft)


def erase_draft(db: Session, draft: ApplicantDraft) -> None:
    """Erase a temporary aggregate without changing the caller's deletion ledger."""
    db.execute(update(BrowserSession).where(BrowserSession.reconciliation_draft_id == draft.id)
        .values(reconciliation_draft_id=None).execution_options(synchronize_session=False))
    db.delete(draft)


def purge_never_submitted_application(db: Session, application: Application) -> None:
    """Physically remove a draft-only application and its access records."""
    _record_deletion(db, record_kind="application", record_id=application.id,
        retention_rule="explicit_application_delete", due_on=pacific_today(), now=datetime.now(UTC))
    erase_application(db, application)


def erase_application(db: Session, application: Application, *, now: datetime | None = None) -> None:
    """Erase an aggregate using schema cascades, preserving unrelated shared output.

    The caller owns policy, deletion receipts and the transaction. The same current
    schema applies to ordinary purges and an upgraded isolated recovery candidate.
    """
    db.execute(update(Feedback).where(Feedback.applicant_id == application.id).values(applicant_id=None))
    affected_results = application_result_ids(db, application.id)
    db.delete(application)
    db.flush()
    prune_unowned_results(db, affected_results, now=now)
