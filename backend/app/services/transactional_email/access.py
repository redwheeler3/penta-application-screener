"""Applicant and committee identity/access emails."""

from app.core.config import Settings
from app.db.models import MagicLinkPurpose, PasswordlessIdentityKind, UserRole
from app.services.email_sender import OutboundEmail

from .layout import (
    _applicant_link_url,
    _committee_magic_link_url,
    _email_shell,
    _with_common_footer,
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


def committee_invitation_email(
    *,
    user_id: int,
    email: str,
    role: UserRole,
    token: str,
    settings: Settings,
) -> OutboundEmail:
    """Welcome a newly allowlisted committee user with their first sign-in link."""
    url = _committee_magic_link_url(settings.frontend_url, token)
    role_name = "an administrator" if role == UserRole.ADMIN else "a committee member"
    introduction = (
        f"An administrator added you to the Penta Application Screener as {role_name}."
    )
    text = _with_common_footer(f"""You've been added to the Penta Application Screener.

{introduction}

Use this private link to sign in:

{url}

If you weren't expecting this invitation, you can ignore this email.""")
    html = _email_shell(
        eyebrow="Committee invitation",
        heading="You've been added to the screener",
        introduction=introduction,
        action_url=url,
        action_label="Sign in to the screener",
        link_notice="If you weren't expecting this invitation, you can ignore this email.",
    )
    return OutboundEmail(
        kind="committee_invitation",
        recipient_id=f"user:{user_id}",
        to=(email,),
        subject="You've been added to the Penta Application Screener",
        text_body=text,
        html_body=html,
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
    url = _committee_magic_link_url(settings.frontend_url, token)
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
