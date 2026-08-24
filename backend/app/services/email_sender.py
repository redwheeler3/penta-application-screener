"""Provider-neutral transactional email with a fail-closed development boundary."""

from __future__ import annotations

from dataclasses import dataclass, replace
from email.utils import parseaddr
from functools import lru_cache
from typing import Protocol
from uuid import uuid4

import httpx

from app.core.config import Settings

DEVELOPMENT_SUBJECT_PREFIX = "[Penta development] "
DEVELOPMENT_EMAIL_DOMAINS = frozenset({"jeffo.net", "pentacoop.com"})
APPLICATIONS_EMAIL_IDENTITY = (
    "Penta Co-operative Housing <applications@pentacoop.com>"
)
SOCKETLABS_TIMEOUT_SECONDS = 10.0


class EmailConfigurationError(RuntimeError):
    pass


class EmailDeliveryError(RuntimeError):
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
        _require_allowed_domain(sender, DEVELOPMENT_EMAIL_DOMAINS)
        _require_allowed_domain(reply_to, DEVELOPMENT_EMAIL_DOMAINS)

    def send(self, message: OutboundEmail) -> str:
        for mailbox in (*message.to, *message.cc, *message.bcc):
            _require_allowed_domain(mailbox, DEVELOPMENT_EMAIL_DOMAINS)
        prefixed = replace(
            message,
            subject=(
                message.subject
                if message.subject.startswith(DEVELOPMENT_SUBJECT_PREFIX)
                else DEVELOPMENT_SUBJECT_PREFIX + message.subject
            ),
        )
        return self.inner.send(prefixed)


class SocketLabsEmailSender:
    """Translate provider-neutral messages into SocketLabs Injection API requests."""

    def __init__(
        self,
        client: httpx.Client,
        *,
        gateway: str,
        server_id: int,
        api_key: str,
    ) -> None:
        self.client = client
        self.gateway = gateway
        self.server_id = server_id
        self.api_key = api_key

    def send(self, message: OutboundEmail) -> str:
        message_id = uuid4().hex
        provider_message: dict[str, object] = {
            "To": _recipients(message.to),
            "From": _recipient(APPLICATIONS_EMAIL_IDENTITY),
            "ReplyTo": _recipient(APPLICATIONS_EMAIL_IDENTITY),
            "Subject": message.subject,
            "TextBody": message.text_body,
            "MessageId": message_id,
        }
        if message.html_body is not None:
            provider_message["HtmlBody"] = message.html_body
        if message.cc:
            provider_message["CC"] = _recipients(message.cc)
        if message.bcc:
            provider_message["BCC"] = _recipients(message.bcc)

        response = self.client.post(
            self.gateway,
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "ServerId": self.server_id,
                "APIKey": self.api_key,
                "Messages": [provider_message],
            },
        )
        response.raise_for_status()
        try:
            result = response.json()
        except ValueError as error:
            raise EmailDeliveryError("SocketLabs returned invalid JSON.") from error
        if result.get("ErrorCode") != "Success":
            raise EmailDeliveryError("SocketLabs rejected the message.")
        return message_id


def build_email_sender(
    settings: Settings, *, client: httpx.Client | None = None
) -> EmailSender:
    if settings.email_delivery_mode == "capture":
        return CapturedEmailSender()

    server_id = _socketlabs_server_id(settings.socketlabs_server_id)
    if not settings.socketlabs_injection_api_key:
        raise EmailConfigurationError("The SocketLabs Injection API key is not configured.")

    sender: EmailSender = SocketLabsEmailSender(
        client or httpx.Client(timeout=SOCKETLABS_TIMEOUT_SECONDS),
        gateway=_socketlabs_gateway(settings.socketlabs_gateway),
        server_id=server_id,
        api_key=settings.socketlabs_injection_api_key,
    )
    if settings.email_delivery_mode == "development":
        return DevelopmentEmailSender(
            sender,
            sender=APPLICATIONS_EMAIL_IDENTITY,
            reply_to=APPLICATIONS_EMAIL_IDENTITY,
        )
    return sender


@lru_cache
def get_email_sender() -> EmailSender:
    """One reusable sender dependency for the process."""
    from app.core.config import get_settings

    return build_email_sender(get_settings())


def _mailbox(value: str) -> str:
    return _parse_mailbox(value)[1]


def _parse_mailbox(value: str) -> tuple[str, str]:
    if "\r" in value or "\n" in value:
        raise EmailConfigurationError("Invalid email mailbox.")
    friendly_name, address = parseaddr(value, strict=True)
    if not address or address.count("@") != 1:
        raise EmailConfigurationError("Invalid email mailbox.")
    return friendly_name, address


def _recipient(value: str) -> dict[str, str]:
    friendly_name, address = _parse_mailbox(value)
    recipient = {"EmailAddress": address}
    if friendly_name:
        recipient["FriendlyName"] = friendly_name
    return recipient


def _recipients(values: tuple[str, ...]) -> list[dict[str, str]]:
    return [_recipient(value) for value in values]


def _socketlabs_server_id(value: str) -> int:
    try:
        server_id = int(value)
    except ValueError as error:
        raise EmailConfigurationError(
            "The SocketLabs Server ID must be configured as a positive integer."
        ) from error
    if server_id <= 0:
        raise EmailConfigurationError(
            "The SocketLabs Server ID must be configured as a positive integer."
        )
    return server_id


def _socketlabs_gateway(value: str) -> str:
    gateway = httpx.URL(value)
    if gateway.scheme != "https" or not gateway.host:
        raise EmailConfigurationError("The SocketLabs gateway must be an HTTPS URL.")
    return str(gateway)


def _require_allowed_domain(value: str, allowed_domains: frozenset[str]) -> None:
    domain = _mailbox(value).rsplit("@", 1)[1].casefold()
    if domain not in allowed_domains:
        allowed = " or ".join(sorted(allowed_domains))
        raise EmailConfigurationError(
            f"Live development email is restricted to {allowed}."
        )
