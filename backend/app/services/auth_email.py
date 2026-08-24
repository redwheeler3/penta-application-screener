"""Transactional email copy for applicant and committee access links."""

from html import escape
from urllib.parse import quote

from app.core.config import Settings
from app.db.models import PasswordlessIdentityKind
from app.services.email_sender import OutboundEmail


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
    html = f"""<p>Use this secure link to return to your Penta housing application:</p>
<p><a href="{escape(url, quote=True)}">Return to your application</a></p>
<p>The link expires in {settings.magic_link_lifetime_minutes} minutes and can be used once. If you did not request it, you can ignore this email.</p>
<p>This transactional email was sent because this address has or requested access to a Penta application. To stop ordinary application messages, sign in and choose <strong>Delete application</strong>.</p>"""
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

This transactional email was sent because this address has active Penta committee access. Contact a Penta administrator if that access should be removed.
"""
    html = f"""<p>Use this secure link to sign in to the Penta Application Screener:</p>
<p><a href="{escape(url, quote=True)}">Sign in to the screener</a></p>
<p>The link expires in {settings.magic_link_lifetime_minutes} minutes and can be used once. If you did not request it, you can ignore this email.</p>
<p>This transactional email was sent because this address has active Penta committee access. Contact a Penta administrator if that access should be removed.</p>"""
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
