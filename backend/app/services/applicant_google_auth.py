"""Resolve a verified Google identity to one current applicant application."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.text import normalize_email
from app.core.time import as_utc
from app.db.models import Application
from app.schemas.applicant.answers import (
    AddressAnswers,
    EssayAnswers,
    WorkingApplicationAnswers,
    WorkingCoApplicantAnswers,
    WorkingEmploymentAnswers,
    WorkingPersonAnswers,
)
from app.services.applicant_drafts import (
    latest_pending_draft_for_email,
    revoke_other_pending_drafts,
)
from app.services.intake import create_application
from app.services.opening_participation import (
    applicant_opening_states,
    application_is_editable,
)
from app.services.retention import retention_due_for_opening_ids


class ApplicantGoogleIdentityConflict(ValueError):
    """The Google subject and verified email do not identify the same application."""


class NewApplicationsUnavailable(ValueError):
    """A new Google identity cannot create an application in the current lifecycle."""


def claim_or_create_google_application(
    db: Session,
    *,
    google_subject: str,
    email: str,
    now: datetime | None = None,
) -> Application:
    """Attach Google to one existing, claimed-draft, or new application."""
    now = now or datetime.now(UTC)
    normalized_email = normalize_email(email)
    subject_application = db.scalar(
        select(Application).where(Application.google_subject == google_subject)
    )
    email_application = db.scalar(
        select(Application).where(
            Application.primary_email == normalized_email,
            Application.withdrawn_at.is_(None),
        )
    )

    if subject_application is not None and (
        subject_application.withdrawn_at is not None
        or subject_application.primary_email != normalized_email
    ):
        raise ApplicantGoogleIdentityConflict(
            "Google account email does not match its applicant application"
        )
    if (
        email_application is not None
        and email_application.google_subject is not None
        and email_application.google_subject != google_subject
    ):
        raise ApplicantGoogleIdentityConflict(
            "Applicant application is linked to another Google account"
        )
    if (
        subject_application is not None
        and email_application is not None
        and subject_application.id != email_application.id
    ):
        raise ApplicantGoogleIdentityConflict(
            "Google subject and email identify different applicant applications"
        )

    application = subject_application or email_application
    if application is not None and not application_is_editable(
        applicant_opening_states(db, application)
    ):
        raise NewApplicationsUnavailable
    if application is None:
        available_opening_ids = _open_application_ids(db)
        if not available_opening_ids:
            raise NewApplicationsUnavailable
        application = _claim_pending_draft(db, normalized_email, now=now)
        if application is None:
            application = create_application(
                db,
                normalized_email,
                _empty_working_answers(normalized_email),
                saved_at=now,
                opening_ids=[],
            )
            application.retention_due_on = retention_due_for_opening_ids(
                db, available_opening_ids
            )

    application.google_subject = google_subject
    db.flush()
    return application


def _claim_pending_draft(
    db: Session,
    email: str,
    *,
    now: datetime,
) -> Application | None:
    draft = latest_pending_draft_for_email(db, email, now=now)
    if draft is None or draft.working_answers is None:
        return None
    try:
        answers = WorkingApplicationAnswers.model_validate(draft.working_answers)
    except ValueError:
        return None
    application = create_application(
        db,
        email,
        answers,
        saved_at=as_utc(draft.saved_at),
        opening_ids=draft.working_opening_ids,
    )
    draft.application_id = application.id
    draft.resolved_at = now
    revoke_other_pending_drafts(db, draft, now=now)
    return application


def _open_application_ids(db: Session) -> list[int]:
    return [
        state.opening.id
        for state in applicant_opening_states(db, None)
        if state.can_select
    ]


def _empty_working_answers(email: str) -> WorkingApplicationAnswers:
    empty_employment = WorkingEmploymentAnswers()
    return WorkingApplicationAnswers(
        applicant=WorkingPersonAnswers(email=email),
        co_applicant=WorkingCoApplicantAnswers(),
        current_address=AddressAnswers(
            street="",
            street_2=None,
            city="",
            province_or_state="BC",
            postal_or_zip_code="",
            country="Canada",
        ),
        essays=EssayAnswers(
            household_introduction="",
            skills_to_contribute="",
            previous_coop_experience="",
            why_coop="",
        ),
        applicant_employment=empty_employment,
        co_applicant_employment=WorkingEmploymentAnswers(),
    )
