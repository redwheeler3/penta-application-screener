"""Transactional email copy for applicant and committee access links."""

from html import escape
from urllib.parse import quote

from app.core.config import Settings
from app.db.models import MagicLinkPurpose, PasswordlessIdentityKind
from app.services.email_sender import OutboundEmail

BRAND_LOGO_URL = "https://www.pentacoop.com/email-house.png"
VACANCY_LIST_URL = "https://www.pentacoop.com/apply.html"
COMMON_FOOTER_TEXT = """This email address is not monitored.

Click here to permanently unsubscribe: {{HsUnsubscribe}}. Penta will no longer be able to email you, including links used to sign in."""
COMMON_FOOTER_HTML = (
    "<span>This email address is not monitored.</span>"
    '<br><strong style="display:inline-block;margin-top:8px;"><HsUnsubscribe>'
    "Click here to permanently unsubscribe.</HsUnsubscribe></strong> "
    "<span>Penta will no longer be able to email you, including links used to sign in.</span>"
)


def application_confirmation_email(
    *,
    application_id: int,
    email: str,
    token: str,
    submitted: bool,
    settings: Settings,
) -> OutboundEmail:
    url = _applicant_link_url(settings.applicant_frontend_url, token)
    state = "submitted" if submitted else "saved"
    heading = f"Your application has been {state}"
    introduction = (
        "Your application is now available to the membership committee."
        if submitted
        else "Your private application draft has been saved."
    )
    text = _with_common_footer(f"""{heading}.

{introduction}

Use this link to open your application:

{url}

""")
    html = _email_shell(
        eyebrow="Application update",
        heading=heading,
        introduction=introduction,
        action_url=url,
        action_label="Open your application",
        link_notice=None,
    )
    return OutboundEmail(
        kind=f"application_{state}",
        recipient_id=f"application:{application_id}",
        to=(email,),
        subject=heading,
        text_body=text,
        html_body=html,
    )


def magic_link_email(
    *,
    identity_kind: PasswordlessIdentityKind,
    purpose: MagicLinkPurpose,
    recipient_id: int,
    email: str,
    token: str,
    settings: Settings,
) -> OutboundEmail:
    if purpose == MagicLinkPurpose.EMAIL_CHANGE:
        return _email_change_confirmation_email(
            recipient_id=recipient_id,
            email=email,
            token=token,
            settings=settings,
        )
    if identity_kind == PasswordlessIdentityKind.APPLICANT:
        return _applicant_magic_link_email(
            recipient_id=recipient_id,
            email=email,
            token=token,
            settings=settings,
        )
    return _committee_magic_link_email(
        recipient_id=recipient_id,
        email=email,
        token=token,
        settings=settings,
    )


def _email_change_confirmation_email(
    *, recipient_id: int, email: str, token: str, settings: Settings
) -> OutboundEmail:
    url = _applicant_link_url(settings.applicant_frontend_url, token)
    introduction = "Confirm this address to use it for your Penta housing application."
    ignored_change_notice = (
        "If you didn't request this change, ignore this email. Your application email "
        "will not change unless you confirm it."
    )
    text = _with_common_footer(f"""Confirm your new application email address:

{url}

{ignored_change_notice}""")
    html = _email_shell(
        eyebrow="Application security",
        heading="Confirm your new email address",
        introduction=introduction,
        action_url=url,
        action_label="Confirm email address",
        link_notice=ignored_change_notice,
    )
    return OutboundEmail(
        kind="application_email_change_confirmation",
        recipient_id=f"application:{recipient_id}",
        to=(email,),
        subject="Confirm your new Penta application email",
        text_body=text,
        html_body=html,
    )


def email_change_notice_email(
    *, application_id: int, old_email: str, new_email: str
) -> OutboundEmail:
    introduction = f"Your Penta application email address was changed to {new_email}."
    notice = (
        "If you made this change, no action is needed. If you didn't, email Penta "
        "Tech Support at techsupport@pentacoop.com."
    )
    text = _with_common_footer(f"""{introduction}

{notice}""")
    html = _email_shell(
        eyebrow="Application security",
        heading="Your application email was changed",
        introduction=introduction,
        action_url=None,
        action_label=None,
        link_notice=notice,
    )
    return OutboundEmail(
        kind="application_email_changed",
        recipient_id=f"application:{application_id}",
        to=(old_email,),
        subject="Your Penta application email was changed",
        text_body=text,
        html_body=html,
    )


def application_deleted_email(*, application_id: int, email: str) -> OutboundEmail:
    heading = "Your application has been deleted"
    introduction = (
        "Your Penta housing application has been deleted from our system."
    )
    invitation = (
        "Penta doesn't keep a waitlist. If you'd like to hear when another unit becomes "
        "available, you're welcome to join our vacancy notification list."
    )
    text = _with_common_footer(f"""{heading}.

{introduction}

{invitation}

{VACANCY_LIST_URL}""")
    html = _email_shell(
        eyebrow="Application update",
        heading=heading,
        introduction=introduction,
        action_url=VACANCY_LIST_URL,
        action_label="Join the vacancy notification list",
        link_notice=invitation,
    )
    return OutboundEmail(
        kind="application_deleted",
        recipient_id=f"application:{application_id}",
        to=(email,),
        subject=heading,
        text_body=text,
        html_body=html,
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
        subject=heading,
        text_body=text,
        html_body=html,
    )


def unsuccessful_application_email(
    *, application_id: int, email: str, opening_labels: list[str]
) -> OutboundEmail:
    heading = "An update on your Penta application"
    introduction = (
        "Thank you for the time you took to apply. We're sorry to let you know that "
        f"your household was not selected for {_natural_list(opening_labels)}. We wish "
        "you all the best in your housing search."
    )
    notice = (
        "If you'd like to hear when another unit becomes available, you're welcome "
        "to join our vacancy notification list."
    )
    text = _with_common_footer(f"""{heading}.

{introduction}

{notice}

{VACANCY_LIST_URL}""")
    html = _email_shell(
        eyebrow="Application update",
        heading=heading,
        introduction=introduction,
        action_url=VACANCY_LIST_URL,
        action_label="Join the vacancy notification list",
        link_notice=notice,
    )
    return OutboundEmail(
        kind="application_unsuccessful",
        recipient_id=f"application:{application_id}",
        to=(email,),
        subject=heading,
        text_body=text,
        html_body=html,
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
        "We're emailing because you have a current Penta housing application. "
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
        subject=f"A new {unit_size} opening may match your household",
        text_body=text,
        html_body=html,
    )


def _natural_list(items: list[str]) -> str:
    if not items:
        raise ValueError("an unsuccessful notice requires at least one opening")
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} or {items[1]}"
    return f"{', '.join(items[:-1])}, or {items[-1]}"


def _applicant_magic_link_email(
    *, recipient_id: int, email: str, token: str, settings: Settings
) -> OutboundEmail:
    url = _applicant_link_url(settings.applicant_frontend_url, token)
    text = _with_common_footer(f"""Review or update your Penta housing application:

{url}

If you did not request it, you can ignore this email.""")
    html = _email_shell(
        eyebrow="Application access",
        heading="Continue your application",
        introduction="Review or update your Penta housing application.",
        action_url=url,
        action_label="Open application",
        link_notice=None,
    )
    return OutboundEmail(
        kind="applicant_magic_link",
        recipient_id=f"application:{recipient_id}",
        to=(email,),
        subject="Continue your Penta application",
        text_body=text,
        html_body=html,
    )


def _committee_magic_link_email(
    *, recipient_id: int, email: str, token: str, settings: Settings
) -> OutboundEmail:
    url = _magic_link_url(settings.frontend_url, token)
    text = _with_common_footer(f"""Use this link to sign in to the Penta Application Screener:

{url}

If you did not request it, you can ignore this email.""")
    html = _email_shell(
        eyebrow="Member access",
        heading="Sign in to the screener",
        introduction="Use the button below to sign in to the Penta Application Screener.",
        action_url=url,
        action_label="Sign in to the screener",
        link_notice=None,
    )
    return OutboundEmail(
        kind="committee_magic_link",
        recipient_id=f"user:{recipient_id}",
        to=(email,),
        subject="Sign in to the Penta Application Screener",
        text_body=text,
        html_body=html,
    )


def _magic_link_url(frontend_url: str, token: str) -> str:
    # Keep the credential in the fragment: browsers do not send fragments in HTTP requests,
    # server logs, or Referer headers. The SPA exchanges it with POST, then removes it.
    return _fragment_url(frontend_url, "magic-link", token)


def _applicant_link_url(frontend_url: str, token: str) -> str:
    return _fragment_url(frontend_url, "applicant-link", token)


def _fragment_url(frontend_url: str, key: str, token: str) -> str:
    return f"{frontend_url.rstrip('/')}#{key}={quote(token, safe='')}"


def _with_common_footer(body: str) -> str:
    return f"{body.rstrip()}\n\n{COMMON_FOOTER_TEXT}\n"


def _opening_details_text(
    *,
    housing_charge: str,
    move_in_date: str,
    close_date: str,
    household_summary: str,
) -> str:
    return "\n".join(
        (
            f"Housing charge: {housing_charge}",
            f"Expected move-in: {move_in_date}",
            f"Applications close: {close_date}",
            f"Household: {household_summary}",
        )
    )


def _opening_email_shell(
    *,
    eyebrow: str,
    heading: str,
    introduction: str,
    unit_size: str,
    housing_charge: str,
    move_in_date: str,
    close_date: str,
    household_summary: str,
    action_url: str,
    action_label: str,
    primary_notice: str,
    list_signup_invitation: bool,
    closing: str,
    list_signup_context: str | None = None,
) -> str:
    safe_action_url = escape(action_url, quote=True)
    rows = (
        ("Housing charge", housing_charge),
        ("Expected move-in", move_in_date),
        ("Applications close", close_date),
        ("Household", household_summary),
    )
    details_html = "".join(
        f"""<tr>
                    <td style="padding:7px 14px 7px 0;color:#6b7280;font-size:14px;vertical-align:baseline;white-space:nowrap;">{escape(label)}</td>
                    <td style="padding:7px 0;color:#111827;font-size:14px;font-weight:700;line-height:1.45;vertical-align:baseline;">{escape(value)}</td>
                  </tr>"""
        for label, value in rows
    )
    signup_html = ""
    if list_signup_invitation:
        signup_context = list_signup_context or ""
        context_html = f"{escape(signup_context)} " if signup_context else ""
        signup_html = f"""<p style="margin:12px 0 0;color:#166534;font-size:14px;line-height:1.55;">{context_html}If you'd like another notice in the future, you can <a href="{escape(VACANCY_LIST_URL, quote=True)}" style="color:#166534;font-weight:700;">sign up again</a>.</p>"""
    body_html = f"""<p style="margin:0 0 22px;color:#4b5563;font-size:16px;line-height:1.6;">{escape(introduction)}</p>
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="margin:0 0 12px;padding:10px 16px;background-color:#f9fafb;border:1px solid #e5e7eb;border-radius:8px;">
                {details_html}
              </table>
              <p style="margin:0 0 24px;color:#6b7280;font-size:14px;line-height:1.55;">The move-in date may shift while we prepare the {escape(unit_size)} home.</p>
              <div style="margin:0 0 24px;padding:16px 18px;background-color:#f0fdf4;border:1px solid #bbf7d0;border-radius:8px;">
                <p style="margin:0;color:#166534;font-size:14px;line-height:1.55;">{escape(primary_notice)}</p>
                {signup_html}
              </div>
              <table role="presentation" cellspacing="0" cellpadding="0" border="0">
                <tr>
                  <td style="border-radius:8px;background-color:#16a34a;">
                    <a href="{safe_action_url}" style="display:inline-block;padding:13px 20px;color:#ffffff;font-size:16px;font-weight:700;text-decoration:none;">{escape(action_label)}</a>
                  </td>
                </tr>
              </table>
              <p style="margin:22px 0 0;color:#4b5563;font-size:15px;line-height:1.6;">{escape(closing)}</p>"""
    return _email_shell(
        eyebrow=eyebrow,
        heading=heading,
        introduction=introduction,
        action_url=None,
        action_label=None,
        link_notice=None,
        custom_content_html=body_html,
    )


def _email_shell(
    *,
    eyebrow: str,
    heading: str,
    introduction: str,
    action_url: str | None,
    action_label: str | None,
    link_notice: str | None,
    custom_content_html: str | None = None,
) -> str:
    action_html = ""
    if action_url is not None and action_label is not None:
        safe_url = escape(action_url, quote=True)
        action_html = f"""<table role="presentation" cellspacing="0" cellpadding="0" border="0">
                <tr>
                  <td style="border-radius:8px;background-color:#16a34a;">
                    <a href="{safe_url}" style="display:inline-block;padding:13px 20px;color:#ffffff;font-size:16px;font-weight:700;text-decoration:none;">{escape(action_label)}</a>
                  </td>
                </tr>
              </table>"""
    notice_html = ""
    if link_notice is not None:
        notice_margin = "24px" if action_html else "0"
        notice_html = f"""<div style="margin-top:{notice_margin};padding:16px 18px;background-color:#f0fdf4;border:1px solid #bbf7d0;border-radius:8px;">
                <p style="margin:0;color:#166534;font-size:14px;line-height:1.55;">{escape(link_notice)}</p>
              </div>"""
    content_html = custom_content_html or f"""<p style="margin:0 0 24px;color:#4b5563;font-size:16px;line-height:1.6;">{escape(introduction)}</p>
              {action_html}
              {notice_html}"""
    return f"""<!doctype html>
<html lang="en">
<body style="margin:0;padding:0;background-color:#f3faf6;color:#111827;font-family:Arial,Helvetica,sans-serif;">
  <div style="display:none;max-height:0;overflow:hidden;opacity:0;">{escape(introduction)}</div>
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background-color:#f3faf6;">
    <tr>
      <td align="center" style="padding:32px 16px;">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="max-width:600px;background-color:#ffffff;border:1px solid #e5e7eb;border-radius:12px;overflow:hidden;">
          <tr>
            <td style="padding:22px 28px;border-bottom:1px solid #e5e7eb;">
              <table role="presentation" cellspacing="0" cellpadding="0" border="0">
                <tr>
                  <td style="padding-right:12px;vertical-align:middle;">
                    <img src="{BRAND_LOGO_URL}" width="36" height="36" alt="" style="display:block;width:36px;height:36px;border:0;">
                  </td>
                  <td style="vertical-align:middle;color:#15803d;font-size:14px;font-weight:800;letter-spacing:0.04em;">PENTA HOUSING CO-OP</td>
                </tr>
              </table>
            </td>
          </tr>
          <tr>
            <td style="padding:32px 28px 28px;">
              <div style="margin-bottom:12px;color:#15803d;font-size:13px;font-weight:800;letter-spacing:0.06em;text-transform:uppercase;">{escape(eyebrow)}</div>
              <h1 style="margin:0 0 16px;color:#111827;font-size:28px;line-height:1.2;">{escape(heading)}</h1>
              {content_html}
            </td>
          </tr>
          <tr>
            <td style="padding:20px 28px;background-color:#f9fafb;border-top:1px solid #e5e7eb;">
              <p style="margin:0;color:#4b5563;font-size:13px;line-height:1.55;">{COMMON_FOOTER_HTML}</p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""
