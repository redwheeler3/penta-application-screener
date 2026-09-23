"""Vacancy and opening announcement emails."""

from app.core.config import Settings
from app.services.email_sender import OutboundEmail

from .layout import (
    VACANCY_LIST_URL,
    _applicant_link_url,
    _opening_details_text,
    _opening_email_shell,
    _with_common_footer,
)


def vacancy_opening_email(
    *,
    email: str,
    unit_size: str,
    housing_charge: str,
    move_in_date: str,
    close_date: str,
    household_summary: str,
) -> OutboundEmail:
    heading = f"A {unit_size} home is available"
    introduction = (
        f"You asked us to let you know when a {unit_size} home became available at "
        "Penta Housing Co-op. Applications are now open."
    )
    details = _opening_details_text(
        housing_charge=housing_charge,
        move_in_date=move_in_date,
        close_date=close_date,
        household_summary=household_summary,
    )
    completed_notice = (
        "Your one-time notification is now complete, and we've removed you from the "
        "vacancy notification list."
    )
    text = _with_common_footer(f"""{heading}.

{introduction}

{details}

The move-in date may shift while we prepare the home.

Apply for this home:

{VACANCY_LIST_URL}

{completed_notice} If you'd like another notice in the future, you can sign up again:

{VACANCY_LIST_URL}

If you're no longer interested, you don't need to do anything.""")
    html = _opening_email_shell(
        eyebrow="Applications open",
        heading=heading,
        introduction=introduction,
        unit_size=unit_size,
        housing_charge=housing_charge,
        move_in_date=move_in_date,
        close_date=close_date,
        household_summary=household_summary,
        action_url=VACANCY_LIST_URL,
        action_label="Apply for this home",
        primary_notice=completed_notice,
        list_signup_invitation=True,
        closing="If you're no longer interested, you don't need to do anything.",
    )
    return OutboundEmail(
        kind="vacancy_opening",
        recipient_id=f"vacancy-list:{email}",
        to=(email,),
        subject=f"Applications are open for a {unit_size} home at Penta",
        text_body=text,
        html_body=html,
    )


def application_opening_email(
    *,
    application_id: int,
    email: str,
    token: str,
    unit_size: str,
    housing_charge: str,
    move_in_date: str,
    close_date: str,
    household_summary: str,
    notification_list_overlap: bool,
    settings: Settings,
) -> OutboundEmail:
    url = _applicant_link_url(settings.applicant_frontend_url, token)
    heading = "A new home is available at Penta"
    introduction = (
        "We're emailing because you previously submitted a Penta housing application. "
        f"A new {unit_size} opening is available and may match your household."
    )
    action_notice = (
        "We have not added your application to this opening. If you'd like to be "
        "considered, review your application and submit it for this opening before "
        "the deadline."
    )
    overlap_notice = (
        f"This email also completes your one-time notification request for {unit_size} "
        "openings. We've removed you from the vacancy notification list."
    )
    details = _opening_details_text(
        housing_charge=housing_charge,
        move_in_date=move_in_date,
        close_date=close_date,
        household_summary=household_summary,
    )
    overlap_text = ""
    if notification_list_overlap:
        overlap_text = f"""

{overlap_notice} You can sign up again if you'd like another notice in the future:

{VACANCY_LIST_URL}
"""
    text = _with_common_footer(f"""{heading}.

{introduction}

{details}

The move-in date may shift while we prepare the home.

{action_notice}

Review and submit your application:

{url}
{overlap_text}
If you're not interested in this opening, you don't need to do anything. Ignoring this email will not change your participation in any other opening.""")
    html = _opening_email_shell(
        eyebrow="Application update",
        heading=heading,
        introduction=introduction,
        unit_size=unit_size,
        housing_charge=housing_charge,
        move_in_date=move_in_date,
        close_date=close_date,
        household_summary=household_summary,
        action_url=url,
        action_label="Review and submit your application",
        primary_notice=action_notice,
        list_signup_invitation=notification_list_overlap,
        list_signup_context=overlap_notice if notification_list_overlap else None,
        closing=(
            "If you're not interested in this opening, you don't need to do anything. "
            "Ignoring this email will not change your participation in any other opening."
        ),
    )
    return OutboundEmail(
        kind=(
            "application_opening_with_vacancy_notice"
            if notification_list_overlap
            else "application_opening"
        ),
        recipient_id=f"application:{application_id}",
        to=(email,),
        subject=f"A new {unit_size} home at Penta may match your household",
        text_body=text,
        html_body=html,
    )
