"""Transactional email templates grouped by recipient journey."""

from .access import (
    committee_invitation_email,
    email_change_notice_email,
    magic_link_email,
)
from .applicant import (
    application_confirmation_email,
    application_unavailable_email,
    selected_application_locked_email,
    unsuccessful_application_email,
)
from .openings import application_opening_email, vacancy_opening_email
from .types import ApplicationOpeningTimeline

__all__ = [
    "ApplicationOpeningTimeline",
    "application_confirmation_email",
    "application_opening_email",
    "application_unavailable_email",
    "committee_invitation_email",
    "email_change_notice_email",
    "magic_link_email",
    "selected_application_locked_email",
    "unsuccessful_application_email",
    "vacancy_opening_email",
]
