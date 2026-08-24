"""Transactional email copy for applicant and committee access links."""

from html import escape
from urllib.parse import quote

from app.core.config import Settings
from app.db.models import PasswordlessIdentityKind
from app.services.email_sender import OutboundEmail

BRAND_LOGO_URL = "https://www.pentacoop.com/house-favicon.png"


def magic_link_email(
    *,
    identity_kind: PasswordlessIdentityKind,
    recipient_id: int,
    email: str,
    token: str,
    settings: Settings,
) -> OutboundEmail:
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


def _applicant_magic_link_email(
    *, recipient_id: int, email: str, token: str, settings: Settings
) -> OutboundEmail:
    url = _magic_link_url(settings.applicant_frontend_url, token)
    application_url = settings.applicant_frontend_url.rstrip("/")
    text = f"""Use this secure link to return to your Penta housing application:

{url}

The link expires in {settings.magic_link_lifetime_minutes} minutes and can be used once. If you did not request it, you can ignore this email.

This transactional email was sent because this address has or requested access to a Penta application. To stop ordinary application messages, sign in and choose Delete application: {application_url}
"""
    html = _email_shell(
        eyebrow="Application access",
        heading="Return to your application",
        introduction="Use the secure button below to return to your Penta housing application.",
        action_url=url,
        action_label="Return to your application",
        lifetime_minutes=settings.magic_link_lifetime_minutes,
        footer_html=(
            "This transactional email was sent because this address has or requested access "
            "to a Penta application. To stop ordinary application messages, sign in and "
            "choose <strong>Delete application</strong>."
        ),
    )
    return OutboundEmail(
        kind="applicant_magic_link",
        recipient_id=f"application:{recipient_id}",
        to=(email,),
        subject="Return to your Penta application",
        text_body=text,
        html_body=html,
    )


def _committee_magic_link_email(
    *, recipient_id: int, email: str, token: str, settings: Settings
) -> OutboundEmail:
    url = _magic_link_url(settings.frontend_url, token)
    text = f"""Use this secure link to sign in to the Penta Application Screener:

{url}

The link expires in {settings.magic_link_lifetime_minutes} minutes and can be used once. If you did not request it, you can ignore this email.

This transactional email was sent because this address has active Penta committee access. Contact Penta Tech Support at techsupport@pentacoop.com if that access should be removed.
"""
    html = _email_shell(
        eyebrow="Member access",
        heading="Sign in to the screener",
        introduction="Use the secure button below to sign in to the Penta Application Screener.",
        action_url=url,
        action_label="Sign in to the screener",
        lifetime_minutes=settings.magic_link_lifetime_minutes,
        footer_html=(
            "This transactional email was sent because this address has active Penta committee "
            'access. Contact <a href="mailto:techsupport@pentacoop.com" HsTracking="false" '
            'style="color:#15803d;font-weight:700;">Penta Tech Support</a> if that access '
            "should be removed."
        ),
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
    return f"{frontend_url.rstrip('/')}#magic-link={quote(token, safe='')}"


def _email_shell(
    *,
    eyebrow: str,
    heading: str,
    introduction: str,
    action_url: str,
    action_label: str,
    lifetime_minutes: int,
    footer_html: str,
) -> str:
    safe_url = escape(action_url, quote=True)
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
                  <td style="vertical-align:middle;color:#16a34a;font-size:14px;font-weight:800;letter-spacing:0.04em;">PENTA HOUSING CO-OP</td>
                </tr>
              </table>
            </td>
          </tr>
          <tr>
            <td style="padding:32px 28px 28px;">
              <div style="margin-bottom:12px;color:#15803d;font-size:13px;font-weight:800;letter-spacing:0.06em;text-transform:uppercase;">{escape(eyebrow)}</div>
              <h1 style="margin:0 0 16px;color:#111827;font-size:28px;line-height:1.2;">{escape(heading)}</h1>
              <p style="margin:0 0 24px;color:#4b5563;font-size:16px;line-height:1.6;">{escape(introduction)}</p>
              <table role="presentation" cellspacing="0" cellpadding="0" border="0">
                <tr>
                  <td style="border-radius:8px;background-color:#16a34a;">
                    <a href="{safe_url}" HsTracking="false" style="display:inline-block;padding:13px 20px;color:#ffffff;font-size:16px;font-weight:700;text-decoration:none;">{escape(action_label)}</a>
                  </td>
                </tr>
              </table>
              <div style="margin-top:24px;padding:16px 18px;background-color:#f0fdf4;border:1px solid #bbf7d0;border-radius:8px;">
                <p style="margin:0;color:#166534;font-size:14px;line-height:1.55;"><strong>This link expires in {lifetime_minutes} minutes</strong> and can be used once. If you did not request it, you can safely ignore this email.</p>
              </div>
            </td>
          </tr>
          <tr>
            <td style="padding:20px 28px;background-color:#f9fafb;border-top:1px solid #e5e7eb;">
              <p style="margin:0;color:#4b5563;font-size:13px;line-height:1.55;">{footer_html}</p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""
