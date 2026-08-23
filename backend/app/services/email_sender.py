"""Provider-neutral transactional email with a fail-closed development boundary."""

from __future__ import annotations

from dataclasses import dataclass, replace
from email.utils import parseaddr
from typing import Protocol

from app.core.config import Settings

DEVELOPMENT_SUBJECT_PREFIX = "[Penta development] "


class EmailConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class OutboundEmail:
    kind: str
    recipient_id: str
    to: tuple[str, ...]
    subject: str
    text_body: str
    html_body: str | None = None
    cc: tuple[str, ...] = ()
    bcc: tuple[str, ...] = ()


class EmailSender(Protocol):
    def send(self, message: OutboundEmail) -> str: ...


class CapturedEmailSender:
    """Test/local sender: capture complete messages in memory and perform no I/O."""

    def __init__(self) -> None:
        self.messages: list[OutboundEmail] = []

    def send(self, message: OutboundEmail) -> str:
        self.messages.append(message)
        return f"captured-{len(self.messages)}"


class DevelopmentEmailSender:
    """Guard live development delivery before delegating to any provider."""

    def __init__(self, inner: EmailSender, *, sender: str, reply_to: str) -> None:
        self.inner = inner
        _require_domain(sender, "jeffo.net")
        _require_domain(reply_to, "jeffo.net")

    def send(self, message: OutboundEmail) -> str:
        for mailbox in (*message.to, *message.cc, *message.bcc):
            _require_domain(mailbox, "jeffo.net")
        prefixed = replace(
            message,
            subject=(
                message.subject
                if message.subject.startswith(DEVELOPMENT_SUBJECT_PREFIX)
                else DEVELOPMENT_SUBJECT_PREFIX + message.subject
            ),
        )
        return self.inner.send(prefixed)


class SesEmailSender:
    """Small adapter over the SES v1 send_email shape."""

    def __init__(self, client, *, sender: str, reply_to: str) -> None:
        self.client = client
        self.sender = _mailbox(sender)
        self.reply_to = _mailbox(reply_to)

    def send(self, message: OutboundEmail) -> str:
        body: dict[str, dict[str, str]] = {
            "Text": {"Charset": "UTF-8", "Data": message.text_body}
        }
        if message.html_body is not None:
            body["Html"] = {"Charset": "UTF-8", "Data": message.html_body}
        destination = {"ToAddresses": [_mailbox(value) for value in message.to]}
        if message.cc:
            destination["CcAddresses"] = [_mailbox(value) for value in message.cc]
        if message.bcc:
            destination["BccAddresses"] = [_mailbox(value) for value in message.bcc]
        response = self.client.send_email(
            Source=self.sender,
            Destination=destination,
            ReplyToAddresses=[self.reply_to],
            Message={
                "Subject": {"Charset": "UTF-8", "Data": message.subject},
                "Body": body,
            },
        )
        return str(response["MessageId"])


def build_email_sender(settings: Settings, *, ses_client=None) -> EmailSender:
    if settings.email_delivery_mode == "capture":
        return CapturedEmailSender()
    if not settings.email_sender or not settings.email_reply_to:
        raise EmailConfigurationError("Email sender and Reply-To must be configured.")
    client = ses_client or _ses_client(settings)
    sender: EmailSender = SesEmailSender(
        client,
        sender=settings.email_sender,
        reply_to=settings.email_reply_to,
    )
    if settings.email_delivery_mode == "development_ses":
        return DevelopmentEmailSender(
            sender,
            sender=settings.email_sender,
            reply_to=settings.email_reply_to,
        )
    if _mailbox(settings.email_sender).casefold() != "applications@pentacoop.com":
        raise EmailConfigurationError(
            "Production email must use applications@pentacoop.com."
        )
    _require_domain(settings.email_reply_to, "pentacoop.com")
    return sender


def _ses_client(settings: Settings):
    if not settings.ses_aws_access_key_id or not settings.ses_aws_secret_access_key:
        raise EmailConfigurationError("The dedicated SES credential is not configured.")
    import boto3

    return boto3.client(
        "ses",
        region_name=settings.ses_region,
        aws_access_key_id=settings.ses_aws_access_key_id,
        aws_secret_access_key=settings.ses_aws_secret_access_key,
    )


def _mailbox(value: str) -> str:
    if "\r" in value or "\n" in value:
        raise EmailConfigurationError("Invalid email mailbox.")
    _, address = parseaddr(value, strict=True)
    if not address or address.count("@") != 1:
        raise EmailConfigurationError("Invalid email mailbox.")
    return address


def _require_domain(value: str, expected_domain: str) -> None:
    domain = _mailbox(value).rsplit("@", 1)[1].casefold()
    if domain != expected_domain:
        raise EmailConfigurationError(
            f"Live development email is restricted to {expected_domain}."
        )
