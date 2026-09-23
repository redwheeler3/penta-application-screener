"""Applicant lifecycle and outcome emails."""

from collections.abc import Sequence
from html import escape

from app.core.config import Settings
from app.services.email_sender import OutboundEmail

from .layout import (
    VACANCY_LIST_URL,
    _applicant_link_url,
    _email_shell,
    _natural_list,
    _with_common_footer,
)
from .types import ApplicationOpeningTimeline


def application_confirmation_email(
    *,
    application_id: int,
    email: str,
    token: str,
    submitted: bool,
    opening_timelines: Sequence[ApplicationOpeningTimeline],
    settings: Settings,
) -> OutboundEmail:
    url = _applicant_link_url(settings.applicant_frontend_url, token)
    state = "submitted" if submitted else "saved"
    heading = (
        "Your application has been submitted"
        if submitted
        else "Your application draft has been saved"
    )
    subject = (
        "Your Penta application has been submitted"
        if submitted
        else "Your Penta application draft has been saved"
    )
    if submitted and not opening_timelines:
        raise ValueError("a submitted application email requires an opening timeline")
    introduction = (
        "Thank you for submitting your application to Penta Co-operative Housing."
        if submitted
        else (
            "Your private application draft has been saved. It has not been submitted "
            "to the membership committee."
        )
    )
    self_service = "You can return to the application page to update your application or delete your profile."
    if submitted:
        timeline_text = _application_timeline_text(opening_timelines)
        body = f"""{heading}.

{introduction}

{timeline_text}

{self_service}

Use this link to open your application:

{url}
"""
    else:
        body = f"""{heading}.

{introduction}

Use this link to open your application:

{url}
"""
    text = _with_common_footer(body)
    html = (
        _submitted_application_email_html(
            heading=heading,
            introduction=introduction,
            timelines=opening_timelines,
            self_service=self_service,
            action_url=url,
        )
        if submitted
        else _email_shell(
            eyebrow="Application update",
            heading=heading,
            introduction=introduction,
            action_url=url,
            action_label="Continue your application",
            link_notice=None,
        )
    )
    return OutboundEmail(
        kind=f"application_{state}",
        recipient_id=f"application:{application_id}",
        to=(email,),
        subject=subject,
        text_body=text,
        html_body=html,
    )


def _application_timeline_text(
    timelines: Sequence[ApplicationOpeningTimeline],
) -> str:
    return "\n\n".join(
        f"{timeline.unit_size} home\n{_application_timeline_copy(timeline)}"
        for timeline in timelines
    )


def _application_timeline_copy(timeline: ApplicationOpeningTimeline) -> str:
    return (
        f"If your application is shortlisted, we'll contact you after {timeline.close_date}. "
        "We'll email you as soon as a decision has been made."
    )


def _submitted_application_email_html(
    *,
    heading: str,
    introduction: str,
    timelines: Sequence[ApplicationOpeningTimeline],
    self_service: str,
    action_url: str,
) -> str:
    timeline_html = "".join(
        f"""<div style="margin:0 0 12px;padding:16px 18px;background-color:#f9fafb;border:1px solid #e5e7eb;border-radius:8px;">
                <strong style="display:block;margin-bottom:7px;color:#174f35;font-size:15px;">{escape(timeline.unit_size)} home</strong>
                <p style="margin:0;color:#4b5563;font-size:14px;line-height:1.55;">{escape(_application_timeline_copy(timeline))}</p>
              </div>"""
        for timeline in timelines
    )
    safe_action_url = escape(action_url, quote=True)
    content_html = f"""<p style="margin:0 0 22px;color:#4b5563;font-size:16px;line-height:1.6;">{escape(introduction)}</p>
              {timeline_html}
              <p style="margin:22px 0;color:#4b5563;font-size:15px;line-height:1.6;">{escape(self_service)}</p>
              <table role="presentation" cellspacing="0" cellpadding="0" border="0">
                <tr>
                  <td style="border-radius:8px;background-color:#16a34a;">
                    <a href="{safe_action_url}" style="display:inline-block;padding:13px 20px;color:#ffffff;font-size:16px;font-weight:700;text-decoration:none;">Open your application</a>
                  </td>
                </tr>
              </table>"""
    return _email_shell(
        eyebrow="Application update",
        heading=heading,
        introduction=introduction,
        action_url=None,
        action_label=None,
        link_notice=None,
        custom_content_html=content_html,
    )

def application_unavailable_email(
    *, email: str, application_id: int | None = None
) -> OutboundEmail:
    heading = "Application access isn't available"
    introduction = (
        "There isn't currently an application you can start or update using this email address."
    )
    notice = "Visit Penta's website for vacancy information and notifications."
    text = _with_common_footer(f"""{heading}.

{introduction}

{notice}

{VACANCY_LIST_URL}""")
    html = _email_shell(
        eyebrow="Application update",
        heading=heading,
        introduction=introduction,
        action_url=VACANCY_LIST_URL,
        action_label="View vacancy information",
        link_notice=notice,
    )
    return OutboundEmail(
        kind="application_unavailable",
        recipient_id=(
            f"application:{application_id}" if application_id is not None else "access-request"
        ),
        to=(email,),
        subject="Penta application access isn't available",
        text_body=text,
        html_body=html,
    )


def selected_application_locked_email(
    *, email: str, application_id: int
) -> OutboundEmail:
    heading = "Your application is now closed"
    introduction = (
        "Your household is now a member of Penta, so your application has been "
        "finalized and can no longer be changed online."
    )
    notice = (
        "No action is required. If you believe you received this message by mistake, "
        "email Penta Tech Support at techsupport@pentacoop.com."
    )
    text = _with_common_footer(f"""{heading}.

{introduction}

{notice}""")
    html = _email_shell(
        eyebrow="Application update",
        heading=heading,
        introduction=introduction,
        action_url=None,
        action_label=None,
        link_notice=notice,
    )
    return OutboundEmail(
        kind="application_selected_locked",
        recipient_id=f"application:{application_id}",
        to=(email,),
        subject="Your Penta application is complete",
        text_body=text,
        html_body=html,
    )


def unsuccessful_application_email(
    *, application_id: int, email: str, opening_labels: list[str]
) -> OutboundEmail:
    heading = "An update on your Penta application"
    decision = (
        "Thank you for the time and care you put into your application. We're sorry to "
        "let you know that your household was not selected for "
        f"{_natural_list(opening_labels)}."
    )
    acknowledgement = (
        "We know that applying for housing takes time and effort, and we appreciate "
        "your interest in making Penta your home. We wish you all the best in your "
        "housing search."
    )
    notice = (
        "If you'd like to hear about future openings at Penta, you're welcome to join "
        "our vacancy notification list."
    )
    text = _with_common_footer(f"""{heading}.

{decision}

{acknowledgement}

{notice}

{VACANCY_LIST_URL}""")
    html = _email_shell(
        eyebrow="Application update",
        heading=heading,
        introduction=decision,
        action_url=VACANCY_LIST_URL,
        action_label="Join the vacancy notification list",
        link_notice=notice,
        additional_paragraphs=(acknowledgement,),
    )
    return OutboundEmail(
        kind="application_unsuccessful",
        recipient_id=f"application:{application_id}",
        to=(email,),
        subject=heading,
        text_body=text,
        html_body=html,
    )
