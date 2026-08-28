"""Development-only previews for browser and email presentation review."""

import os

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from app.core.config import Settings, get_settings
from app.core.problems import Problem
from app.db.models import MagicLinkPurpose, PasswordlessIdentityKind
from app.services.auth_email import (
    application_confirmation_email,
    application_opening_email,
    application_unavailable_email,
    application_withdrawn_email,
    email_change_notice_email,
    magic_link_email,
    unsuccessful_application_email,
    vacancy_opening_email,
)
from app.services.email_sender import OutboundEmail

router = APIRouter(prefix="/dev/previews", tags=["development previews"])


class EmailPreview(BaseModel):
    key: str
    title: str
    subject: str
    html: str


@router.get("/emails", response_model=list[EmailPreview])
def email_previews(
    response: Response,
    settings: Settings = Depends(get_settings),
) -> list[EmailPreview]:
    """Render every application email without queueing or delivering it."""
    if settings.email_delivery_mode == "production":
        raise Problem("not_found")
    response.headers["X-Preview-Process"] = str(os.getpid())

    email = "applicant@example.test"
    token = "synthetic-preview-token"
    messages = [
        (
            "application-saved",
            "Application saved",
            application_confirmation_email(
                application_id=1,
                email=email,
                token=token,
                submitted=False,
                settings=settings,
            ),
        ),
        (
            "application-submitted",
            "Application submitted",
            application_confirmation_email(
                application_id=1,
                email=email,
                token=token,
                submitted=True,
                settings=settings,
            ),
        ),
        (
            "applicant-access",
            "Open an application",
            magic_link_email(
                identity_kind=PasswordlessIdentityKind.APPLICANT,
                purpose=MagicLinkPurpose.APPLICANT_ACCESS,
                recipient_id=1,
                email=email,
                token=token,
                settings=settings,
            ),
        ),
        (
            "committee-access",
            "Committee sign-in",
            magic_link_email(
                identity_kind=PasswordlessIdentityKind.COMMITTEE,
                purpose=MagicLinkPurpose.COMMITTEE_ACCESS,
                recipient_id=1,
                email="member@example.test",
                token=token,
                settings=settings,
            ),
        ),
        (
            "email-change-confirmation",
            "Confirm a new application email",
            magic_link_email(
                identity_kind=PasswordlessIdentityKind.APPLICANT,
                purpose=MagicLinkPurpose.EMAIL_CHANGE,
                recipient_id=1,
                email="new-address@example.test",
                token=token,
                settings=settings,
            ),
        ),
        (
            "email-change-notice",
            "Previous-address change notice",
            email_change_notice_email(
                application_id=1,
                old_email=email,
                new_email="new-address@example.test",
            ),
        ),
        (
            "application-withdrawn",
            "Application withdrawn",
            application_withdrawn_email(application_id=1, email=email),
        ),
        (
            "application-unavailable",
            "Application access unavailable",
            application_unavailable_email(application_id=1, email=email),
        ),
        (
            "application-unsuccessful",
            "Application not selected",
            unsuccessful_application_email(
                application_id=1,
                email=email,
                opening_labels=[
                    "the 2-bedroom home (September 30, 2026 move-in)",
                    "the 3-bedroom home (October 31, 2026 move-in)",
                ],
            ),
        ),
        (
            "vacancy-opening-list-only",
            "Opening available, notification list",
            vacancy_opening_email(
                email=email,
                unit_size="3-bedroom",
                housing_charge="$1,226 per month",
                move_in_date="October 1, 2026",
                close_date="July 31, 2026",
                household_summary=(
                    "One or two adults and at least two children under 18"
                ),
            ),
        ),
        (
            "vacancy-opening-application-only",
            "Opening available, current application",
            application_opening_email(
                application_id=1,
                email=email,
                token=token,
                unit_size="3-bedroom",
                housing_charge="$1,226 per month",
                move_in_date="October 1, 2026",
                close_date="July 31, 2026",
                household_summary=(
                    "One or two adults and at least two children under 18"
                ),
                notification_list_overlap=False,
                settings=settings,
            ),
        ),
        (
            "vacancy-opening-overlap",
            "Opening available, application and notification list",
            application_opening_email(
                application_id=1,
                email=email,
                token=token,
                unit_size="3-bedroom",
                housing_charge="$1,226 per month",
                move_in_date="October 1, 2026",
                close_date="July 31, 2026",
                household_summary=(
                    "One or two adults and at least two children under 18"
                ),
                notification_list_overlap=True,
                settings=settings,
            ),
        ),
    ]
    return [_preview(key, title, message) for key, title, message in messages]


def _preview(key: str, title: str, message: OutboundEmail) -> EmailPreview:
    return EmailPreview(
        key=key,
        title=title,
        subject=message.subject,
        html=message.html_body,
    )
