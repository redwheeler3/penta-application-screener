"""Applicant link claims, draft reconciliation, and application access policy."""

from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.problems import Problem
from app.core.text import normalize_email
from app.core.time import as_utc
from app.db.models import (
    ApplicantDraft,
    ApplicantDraftIntent,
    Application,
    MagicLinkPurpose,
    MagicLinkToken,
    PasswordlessIdentityKind,
)
from app.schemas.applicant.answers import (
    CanonicalApplicationAnswers,
    WorkingApplicationAnswers,
)
from app.services.applications.answers import working_answers_for
from app.services.applications.drafts import (
    draft_is_available,
    revoke_application_drafts,
)
from app.services.applications.intake import (
    create_application,
    save_working_copy,
)
from app.services.applications.locking import lock_application
from app.services.applications.selected import application_is_selected
from app.services.auth.passwordless import (
    magic_link_for_token,
)
from app.services.openings.participation import (
    applicant_opening_states,
    application_is_editable,
)


def applicant_link(db: Session, token: str) -> MagicLinkToken | None:
    access_link = magic_link_for_token(
        db,
        token,
        identity_kind=PasswordlessIdentityKind.APPLICANT,
        purpose=MagicLinkPurpose.APPLICANT_ACCESS,
    )
    if access_link is not None:
        return access_link
    return magic_link_for_token(
        db,
        token,
        identity_kind=PasswordlessIdentityKind.APPLICANT,
        purpose=MagicLinkPurpose.EMAIL_CHANGE,
    )


@dataclass(frozen=True)
class ClaimedApplicantLink:
    application: Application | None
    pending_intent: ApplicantDraftIntent | None = None
    previous_email: str | None = None
    reconciliation_draft: ApplicantDraft | None = None
    state: str = "valid"
    google_disconnected: bool = False


def claim_link_target(db: Session, link: MagicLinkToken) -> ClaimedApplicantLink:
    if link.purpose == MagicLinkPurpose.EMAIL_CHANGE:
        return _claim_email_change(db, link)
    if link.application_id is not None:
        application = _active_application(db, link.application_id)
        if application is not None and not application_is_editable(db, application):
            return ClaimedApplicantLink(None, state="unavailable")
        return ClaimedApplicantLink(
            application,
            state="valid" if application is not None else "abandoned",
        )
    draft = db.get(ApplicantDraft, link.applicant_draft_id, populate_existing=True) if link.applicant_draft_id is not None else None
    if draft is None or not draft_is_available(draft):
        return ClaimedApplicantLink(None, state="abandoned")
    application = _active_application(db, draft.application_id)
    if application is None:
        application = db.scalar(
            select(Application).where(
                Application.primary_email == draft.email,
                Application.withdrawn_at.is_(None),
            )
        )
    if application is not None:
        if application.primary_email != draft.email:
            return ClaimedApplicantLink(None, state="abandoned")
        if not application_is_editable(db, application):
            return ClaimedApplicantLink(None, state="unavailable")
        draft.application_id = application.id
        if pending_copy_needed(application, draft):
            return ClaimedApplicantLink(
                application,
                draft.intent,
                reconciliation_draft=draft,
            )
        _resolve_pending_draft(application, draft)
        return ClaimedApplicantLink(application, draft.intent)
    if not new_applications_are_open(db):
        return ClaimedApplicantLink(None, state="unavailable")
    answers = draft_answers(draft)
    if answers is None:
        return ClaimedApplicantLink(None, state="abandoned")
    application = create_application(
        db,
        draft.email,
        answers,
        saved_at=as_utc(draft.saved_at),
        opening_ids=draft.working_opening_ids,
    )
    draft.application_id = application.id
    draft.resolved_at = datetime.now(UTC)
    return ClaimedApplicantLink(application, draft.intent)


def _claim_email_change(db: Session, link: MagicLinkToken) -> ClaimedApplicantLink:
    # Link inspection can have loaded an older answer snapshot before token consumption.
    # Reload under the application write lock before merging only the email change.
    application = lock_application(db, link.application_id)
    if application is None or application.withdrawn_at is not None:
        return ClaimedApplicantLink(None)
    if application_is_selected(db, application.id):
        return ClaimedApplicantLink(None, state="unavailable")
    conflicting = db.scalar(
        select(Application).where(
            Application.primary_email == link.email,
            Application.id != application.id,
            Application.withdrawn_at.is_(None),
        )
    )
    if conflicting is not None:
        return ClaimedApplicantLink(application, state="email_in_use")

    old_email = application.primary_email
    google_disconnected = application.google_subject is not None
    answers = working_answers_for(application)
    if answers is not None:
        updated_applicant = answers.applicant.model_copy(update={"email": link.email})
        updated_answers = answers.model_copy(update={"applicant": updated_applicant})
        save_working_copy(application, updated_answers, saved_at=datetime.now(UTC))
    application.primary_email = link.email
    application.google_subject = None
    revoke_application_drafts(db, application.id, now=datetime.now(UTC))
    return ClaimedApplicantLink(
        application,
        previous_email=old_email,
        google_disconnected=google_disconnected,
    )


def link_targets_other_application(
    link: MagicLinkToken, current: Application | None
) -> bool:
    if current is None:
        return False
    target_id = link.application_id
    if target_id is None and link.applicant_draft is not None:
        target_id = link.applicant_draft.application_id
    if target_id is not None:
        return target_id != current.id
    return normalize_email(current.primary_email) != normalize_email(link.email)


def _resolve_pending_draft(application: Application, draft: ApplicantDraft) -> None:
    """Resolve a pending copy that does not require an applicant choice."""
    answers = draft_answers(draft)
    if answers is not None and working_answers_for(application) is None:
        save_working_copy(
            application,
            answers,
            saved_at=as_utc(draft.saved_at),
            opening_ids=draft.working_opening_ids,
        )
    draft.application_id = application.id
    draft.resolved_at = datetime.now(UTC)


def pending_copy_needed(application: Application, draft: ApplicantDraft) -> bool:
    saved = working_answers_for(application)
    guest = draft_answers(draft)
    if saved is None or guest is None:
        return False
    return (
        saved.model_dump(mode="json") != guest.model_dump(mode="json")
        or set(application.working_opening_ids or []) != set(draft.working_opening_ids or [])
    )


def draft_belongs_to_application(
    draft: ApplicantDraft | None,
    application: Application,
) -> bool:
    return bool(
        draft is not None
        and draft.application_id == application.id
        and draft.email == application.primary_email
        and draft_is_available(draft)
    )


def link_target(db: Session, link: MagicLinkToken) -> Application | ApplicantDraft | None:
    if link.application_id is not None:
        return _active_application(db, link.application_id)
    draft = link.applicant_draft
    if draft is None:
        return None
    if draft.resolved_at is not None and draft.application_id is not None:
        return _active_application(db, draft.application_id)
    return draft if draft_is_available(draft) else None


def application_for_access_target(
    db: Session, target: Application | ApplicantDraft
) -> Application | None:
    if isinstance(target, Application):
        return target
    application = _active_application(db, target.application_id)
    if application is not None:
        return application
    return db.scalar(
        select(Application).where(
            Application.primary_email == target.email,
            Application.withdrawn_at.is_(None),
        )
    )


def access_target_is_editable(
    db: Session, target: Application | ApplicantDraft
) -> bool:
    application = application_for_access_target(db, target)
    if application is not None:
        return application_is_editable(db, application)
    return new_applications_are_open(db)


def _active_application(db: Session, application_id: int | None) -> Application | None:
    application = db.get(Application, application_id, populate_existing=True) if application_id is not None else None
    return application if application is not None and application.withdrawn_at is None else None


def draft_answers(draft: ApplicantDraft | None) -> WorkingApplicationAnswers | None:
    if draft is None or draft.working_answers is None:
        return None
    try:
        return WorkingApplicationAnswers.model_validate(draft.working_answers)
    except ValidationError:
        return None


def pending_email_change(db: Session, application_id: int) -> str | None:
    now = datetime.now(UTC)
    return db.scalar(
        select(MagicLinkToken.email)
        .where(
            MagicLinkToken.application_id == application_id,
            MagicLinkToken.purpose == MagicLinkPurpose.EMAIL_CHANGE,
            MagicLinkToken.consumed_at.is_(None),
            MagicLinkToken.revoked_at.is_(None),
            MagicLinkToken.expires_at > now,
        )
        .order_by(MagicLinkToken.created_at.desc())
    )


def require_new_applications_open(db: Session) -> None:
    if not new_applications_are_open(db):
        raise Problem("applications_closed", detail="Applications are not currently open.")


def new_applications_are_open(db: Session) -> bool:
    return any(state.can_select for state in applicant_opening_states(db, None))


def require_application_editable(db: Session, application: Application) -> None:
    if not application_is_editable(db, application):
        raise Problem("applications_locked", detail="This application cannot be edited right now.")


def require_application_not_selected(db: Session, application: Application) -> None:
    if application_is_selected(db, application.id):
        raise Problem("applications_locked", detail="This application cannot be edited right now.")


def require_matching_email(
    application: Application,
    answers: WorkingApplicationAnswers | CanonicalApplicationAnswers,
) -> None:
    if normalize_email(str(answers.applicant.email)) != normalize_email(
        application.primary_email
    ):
        raise Problem(
            "verified_email_required",
            detail="Use Change email address to update your application email.",
        )


def lock_application_revision(
    db: Session, application: Application, base_revision: int | None
) -> None:
    """Check the database revision and hold its write lock until this transaction ends.

    A conditional no-op UPDATE works with SQLite's writer lock as well as row-locking
    databases. The working-copy save advances the revision in this same transaction;
    a competing save then fails the predicate instead of checking a stale ORM snapshot.
    """
    claimed = db.execute(
        update(Application)
        .where(Application.id == application.id, Application.working_revision == base_revision)
        .values(working_revision=Application.working_revision, updated_at=Application.updated_at)
        .execution_options(synchronize_session=False)
    )
    if claimed.rowcount != 1:
        raise Problem(
            "stale_application",
            detail=(
                "This application was saved in another tab or browser. "
                "Reload the latest saved copy before continuing."
            ),
        )
    db.refresh(application)


def applicant_link_state(
    db: Session, link: MagicLinkToken | None, *, now: datetime | None = None
) -> str:
    """Inspect proof availability without consuming the link or changing the application."""
    now = now or datetime.now(UTC)
    if link is None:
        return "invalid"
    if link.consumed_at is not None:
        state = "used"
    elif link.revoked_at is not None:
        state = "replaced"
    elif as_utc(link.expires_at) <= now:
        state = "expired"
    elif link.applicant_draft is not None and not draft_is_available(link.applicant_draft, now=now):
        state = "abandoned"
    else:
        target = link_target(db, link)
        if target is None:
            state = "abandoned"
        else:
            state = "valid" if access_target_is_editable(db, target) else "unavailable"
    return state
