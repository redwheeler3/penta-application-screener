"""Branded, provider-neutral HTML and plain-text email layout primitives."""

from collections.abc import Sequence
from html import escape
from urllib.parse import quote

BRAND_LOGO_URL = "https://www.pentacoop.com/email-house.png"
VACANCY_LIST_URL = "https://www.pentacoop.com/apply.html"
COMMON_FOOTER_TEXT = """This email address is not monitored.

Sent by Penta Co-operative Housing
1717 Wallace Street, Vancouver, BC V6R 4J7

Click here to permanently unsubscribe: {{HsUnsubscribe}}. Penta will no longer be able to email you, including links used to sign in."""
COMMON_FOOTER_HTML = (
    "<span>This email address is not monitored.</span>"
    '<br><span style="display:inline-block;margin-top:8px;">Sent by Penta Co-operative Housing</span>'
    "<br><span>1717 Wallace Street, Vancouver, BC V6R 4J7</span>"
    '<br><strong style="display:inline-block;margin-top:8px;"><HsUnsubscribe>'
    "Click here to permanently unsubscribe.</HsUnsubscribe></strong> "
    "<span>Penta will no longer be able to email you, including links used to sign in.</span>"
)


def _natural_list(items: list[str]) -> str:
    if not items:
        raise ValueError("an unsuccessful notice requires at least one opening")
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} or {items[1]}"
    return f"{', '.join(items[:-1])}, or {items[-1]}"



def _committee_magic_link_url(frontend_url: str, token: str) -> str:
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
    additional_paragraphs: Sequence[str] = (),
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
    paragraph_html = "".join(
        f'<p style="margin:0 0 24px;color:#4b5563;font-size:16px;line-height:1.6;">{escape(paragraph)}</p>'
        for paragraph in (introduction, *additional_paragraphs)
    )
    content_html = custom_content_html or f"""{paragraph_html}
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
