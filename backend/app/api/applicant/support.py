"""Shared helpers for applicant drafts, identity links, and applications."""

from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import ValidationError
from sqlalchemy import delete as sql_delete
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.problems import Problem
from app.core.text import normalize_email
from app.core.time import as_utc
from app.db.models import (
    ApplicantDraft,
    ApplicantDraftIntent,
    Application,
    BrowserSession,
    EmailDelivery,
    MagicLinkPurpose,
    MagicLinkToken,
    PasswordlessIdentityKind,
)
from app.schemas.applicant_intake import (
    AccessLinkResponse,
    ApplicantOpeningOut,
    PendingCopyOut,
)
from app.schemas.intake import CanonicalApplicationAnswers, WorkingApplicationAnswers
from app.services.applicant_drafts import (
    draft_is_available,
)
from app.services.intake import (
    create_application,
    save_working_copy,
)
from app.services.opening_participation import (
    ApplicantOpeningState,
    applicant_opening_states,
    application_is_editable,
)
from app.services.passwordless_auth import (
    magic_link_for_token,
)


def _purge_never_submitted_application(db: Session, application: Application) -> None:
    """Physically remove a draft-only application and its access records."""
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


def _applicant_link(db: Session, token: str) -> MagicLinkToken | None:
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


def _access_link_response(
    db: Session,
    link: MagicLinkToken | None,
    current: Application | None,
    *,
    now: datetime | None = None,
) -> AccessLinkResponse:
    now = now or datetime.now(UTC)
    if link is None:
        return AccessLinkResponse(state="invalid")
    if link.consumed_at is not None:
        state = "used"
    elif link.revoked_at is not None:
        state = "replaced"
    elif as_utc(link.expires_at) <= now:
        state = "expired"
    elif link.applicant_draft is not None and not draft_is_available(link.applicant_draft, now=now):
        state = "abandoned"
    elif link.purpose == MagicLinkPurpose.APPLICANT_ACCESS:
        target = _link_target(db, link)
        if target is None:
            state = "abandoned"
        else:
            state = "valid" if _access_target_is_editable(db, target) else "unavailable"
    else:
        state = "valid"
    return AccessLinkResponse(
        state=state,
        purpose=link.purpose,
        current_email=current.primary_email if current is not None else None,
        link_email=link.email,
        application_email=(link.application.primary_email if link.application is not None else None),
        switch_required=_link_targets_other_application(link, current),
        application_id=current.id if current is not None else None,
        pending_intent=link.applicant_draft.intent if link.applicant_draft is not None else None,
    )


@dataclass(frozen=True)
class _ClaimedApplicantLink:
    application: Application | None
    pending_intent: ApplicantDraftIntent | None = None
    previous_email: str | None = None
    reconciliation_draft: ApplicantDraft | None = None
    state: str = "valid"


def _claim_link_target(db: Session, link: MagicLinkToken) -> _ClaimedApplicantLink:
    if link.purpose == MagicLinkPurpose.EMAIL_CHANGE:
        return _claim_email_change(db, link)
    if link.application_id is not None:
        return _ClaimedApplicantLink(_active_application(db, link.application_id))
    draft = link.applicant_draft
    if draft is None or not draft_is_available(draft):
        return _ClaimedApplicantLink(None)
    application = _active_application(db, draft.application_id)
    if application is None:
        application = db.scalar(
            select(Application).where(
                Application.primary_email == draft.email,
                Application.deleted_at.is_(None),
            )
        )
    if application is not None:
        draft.application_id = application.id
        if _pending_copy_needed(application, draft):
            return _ClaimedApplicantLink(
                application,
                draft.intent,
                reconciliation_draft=draft,
            )
        _resolve_pending_draft(application, draft)
        return _ClaimedApplicantLink(application, draft.intent)
    answers = _draft_answers(draft)
    if answers is None:
        return _ClaimedApplicantLink(None)
    application = create_application(
        db,
        draft.email,
        answers,
        saved_at=as_utc(draft.saved_at),
        opening_ids=draft.working_opening_ids,
    )
    draft.application_id = application.id
    draft.resolved_at = datetime.now(UTC)
    return _ClaimedApplicantLink(application, draft.intent)


def _claim_email_change(db: Session, link: MagicLinkToken) -> _ClaimedApplicantLink:
    application = _active_application(db, link.application_id)
    if application is None:
        return _ClaimedApplicantLink(None)
    conflicting = db.scalar(
        select(Application).where(
            Application.primary_email == link.email,
            Application.id != application.id,
            Application.deleted_at.is_(None),
        )
    )
    if conflicting is not None:
        return _ClaimedApplicantLink(application, state="email_in_use")

    old_email = application.primary_email
    answers = _stored_answers(application)
    if answers is not None:
        updated_applicant = answers.applicant.model_copy(update={"email": link.email})
        updated_answers = answers.model_copy(update={"applicant": updated_applicant})
        save_working_copy(application, updated_answers, saved_at=datetime.now(UTC))
    application.primary_email = link.email
    return _ClaimedApplicantLink(application, previous_email=old_email)


def _link_targets_other_application(
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
    answers = _draft_answers(draft)
    if answers is not None and _stored_answers(application) is None:
        save_working_copy(
            application,
            answers,
            saved_at=as_utc(draft.saved_at),
            opening_ids=draft.working_opening_ids,
        )
    draft.application_id = application.id
    draft.resolved_at = datetime.now(UTC)


def _pending_copy_needed(application: Application, draft: ApplicantDraft) -> bool:
    saved = _stored_answers(application)
    guest = _draft_answers(draft)
    if saved is None or guest is None:
        return False
    return (
        saved.model_dump(mode="json") != guest.model_dump(mode="json")
        or set(application.working_opening_ids or []) != set(draft.working_opening_ids or [])
    )


def _pending_copy(application: Application, draft: ApplicantDraft) -> PendingCopyOut:
    saved = _stored_answers(application)
    guest = _draft_answers(draft)
    if saved is None or guest is None:
        raise ValueError("pending-copy comparison requires two readable working copies")
    return PendingCopyOut(
        saved_answers=saved,
        saved_opening_ids=list(application.working_opening_ids or []),
        guest_answers=guest,
        guest_opening_ids=list(draft.working_opening_ids or []),
    )


def _draft_belongs_to_application(
    draft: ApplicantDraft | None,
    application: Application,
) -> bool:
    return bool(
        draft is not None
        and draft.application_id == application.id
        and draft_is_available(draft)
    )


def _link_target(db: Session, link: MagicLinkToken) -> Application | ApplicantDraft | None:
    if link.application_id is not None:
        return _active_application(db, link.application_id)
    draft = link.applicant_draft
    if draft is None:
        return None
    if draft.resolved_at is not None and draft.application_id is not None:
        return _active_application(db, draft.application_id)
    return draft if draft_is_available(draft) else None


def _application_for_access_target(
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
            Application.deleted_at.is_(None),
        )
    )


def _access_target_is_editable(
    db: Session, target: Application | ApplicantDraft
) -> bool:
    application = _application_for_access_target(db, target)
    if application is not None:
        return application_is_editable(applicant_opening_states(db, application))
    return _new_applications_are_open(db)


def _active_application(db: Session, application_id: int | None) -> Application | None:
    application = db.get(Application, application_id) if application_id is not None else None
    return application if application is not None and application.deleted_at is None else None


def _draft_answers(draft: ApplicantDraft | None) -> WorkingApplicationAnswers | None:
    if draft is None or draft.working_answers is None:
        return None
    try:
        return WorkingApplicationAnswers.model_validate(draft.working_answers)
    except ValidationError:
        return None


def _pending_email_change(db: Session, application_id: int) -> str | None:
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
def _applicant_opening(state: ApplicantOpeningState) -> ApplicantOpeningOut:
    opening = state.opening
    return ApplicantOpeningOut(
        id=opening.id,
        unit_size_bedrooms=opening.unit_size_bedrooms,
        housing_charge_cents=opening.housing_charge_cents,
        application_open_date=opening.application_open_date.isoformat(),
        application_close_date=opening.application_close_date.isoformat(),
        move_in_date=opening.move_in_date.isoformat(),
        phase=state.phase,
        selected=state.selected,
        participating=state.participating,
        has_participated=state.has_participated,
        can_select=state.can_select,
        can_withdraw=state.can_withdraw,
    )


def _require_new_applications_open(db: Session) -> None:
    if not _new_applications_are_open(db):
        raise Problem("applications_closed", detail="Applications are not currently open.")


def _new_applications_are_open(db: Session) -> bool:
    return any(state.can_select for state in applicant_opening_states(db, None))


def _require_application_editable(db: Session, application: Application) -> None:
    if not application_is_editable(applicant_opening_states(db, application)):
        raise Problem("applications_locked", detail="This application cannot be edited right now.")


def _stored_answers(application: Application) -> WorkingApplicationAnswers | None:
    stored = application.working_answers
    if stored is None and "applicant" in (application.raw_row or {}):
        stored = application.raw_row
    if stored is None:
        return None
    try:
        return WorkingApplicationAnswers.model_validate(stored)
    except ValidationError:
        return None


def _require_matching_email(
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


def _require_current_revision(application: Application, base_revision: int | None) -> None:
    if base_revision != application.working_revision:
        raise Problem(
            "stale_application",
            detail=(
                "This application was saved in another tab or browser. "
                "Reload the latest saved copy before continuing."
            ),
        )
