import pytest

from app.core.config import Settings
from app.services.email_sender import (
    CapturedEmailSender,
    DevelopmentEmailSender,
    EmailConfigurationError,
    EmailDeliveryError,
    OutboundEmail,
    SocketLabsEmailSender,
    build_email_sender,
)


class FakeResponse:
    def __init__(self, payload: dict, *, status_error: Exception | None = None) -> None:
        self.payload = payload
        self.status_error = status_error

    def raise_for_status(self) -> None:
        if self.status_error is not None:
            raise self.status_error

    def json(self) -> dict:
        return self.payload


class FakeHttpClient:
    def __init__(self, payload: dict | None = None) -> None:
        self.response = FakeResponse(payload or {"ErrorCode": "Success"})
        self.calls: list[tuple[str, dict[str, str], dict]] = []

    def post(
        self, url: str, *, headers: dict[str, str], json: dict
    ) -> FakeResponse:
        self.calls.append((url, headers, json))
        return self.response


def _message(**overrides) -> OutboundEmail:
    values = {
        "kind": "return_link",
        "recipient_id": "applicant-1",
        "to": ("person@jeffo.net",),
        "subject": "Return to your application",
        "text_body": "Synthetic transactional email.",
    }
    values.update(overrides)
    return OutboundEmail(**values)


def test_capture_sender_performs_no_provider_call() -> None:
    sender = CapturedEmailSender()
    assert sender.send(_message()) == "captured-1"
    assert sender.messages == [_message()]


def test_capture_is_the_safe_configuration_default() -> None:
    sender = build_email_sender(Settings(_env_file=None))

    assert isinstance(sender, CapturedEmailSender)


def test_socketlabs_adapter_maps_provider_neutral_message() -> None:
    client = FakeHttpClient()
    sender = SocketLabsEmailSender(
        client,
        gateway="https://inject.example.test/email",
        server_id=12345,
        api_key="synthetic-key",
    )

    message_id = sender.send(
        _message(
            to=("Applicant <person@jeffo.net>",),
            cc=("committee@pentacoop.com",),
            bcc=("archive@pentacoop.com",),
            html_body="<p>Synthetic transactional email.</p>",
        )
    )

    assert len(message_id) == 32
    url, headers, payload = client.calls[0]
    assert url == "https://inject.example.test/email"
    assert headers == {"Authorization": "Bearer synthetic-key"}
    assert payload["ServerId"] == 12345
    assert payload["APIKey"] == "synthetic-key"
    provider_message = payload["Messages"][0]
    assert provider_message["MessageId"] == message_id
    assert provider_message["To"] == [
        {"EmailAddress": "person@jeffo.net", "FriendlyName": "Applicant"}
    ]
    assert provider_message["CC"] == [{"EmailAddress": "committee@pentacoop.com"}]
    assert provider_message["BCC"] == [{"EmailAddress": "archive@pentacoop.com"}]
    assert provider_message["From"] == {
        "EmailAddress": "applications@pentacoop.com",
        "FriendlyName": "Penta Co-operative Housing",
    }
    assert provider_message["ReplyTo"] == {
        "EmailAddress": "applications@pentacoop.com",
        "FriendlyName": "Penta Co-operative Housing",
    }
    assert provider_message["TextBody"] == "Synthetic transactional email."
    assert provider_message["HtmlBody"] == "<p>Synthetic transactional email.</p>"


def test_socketlabs_adapter_rejects_provider_warning() -> None:
    sender = SocketLabsEmailSender(
        FakeHttpClient({"ErrorCode": "Warning"}),
        gateway="https://inject.example.test/email",
        server_id=12345,
        api_key="synthetic-key",
    )

    with pytest.raises(EmailDeliveryError):
        sender.send(_message())


@pytest.mark.parametrize("server_id", ["", "invalid", "0", "-1"])
def test_live_delivery_requires_valid_socketlabs_credentials(server_id: str) -> None:
    with pytest.raises(EmailConfigurationError):
        build_email_sender(
            Settings(
                email_delivery_mode="production",
                socketlabs_server_id=server_id,
                socketlabs_injection_api_key="synthetic-key",
                _env_file=None,
            ),
            client=FakeHttpClient(),
        )


def test_live_delivery_requires_socketlabs_api_key() -> None:
    with pytest.raises(EmailConfigurationError):
        build_email_sender(
            Settings(
                email_delivery_mode="production",
                socketlabs_server_id="12345",
                _env_file=None,
            ),
            client=FakeHttpClient(),
        )


def test_live_delivery_requires_https_socketlabs_gateway() -> None:
    with pytest.raises(EmailConfigurationError):
        build_email_sender(
            Settings(
                email_delivery_mode="production",
                socketlabs_server_id="12345",
                socketlabs_injection_api_key="synthetic-key",
                socketlabs_gateway="http://inject.example.test/email",
                _env_file=None,
            ),
            client=FakeHttpClient(),
        )


def test_live_delivery_uses_numeric_socketlabs_server_id() -> None:
    client = FakeHttpClient()
    sender = build_email_sender(
        Settings(
            email_delivery_mode="production",
            socketlabs_server_id="12345",
            socketlabs_injection_api_key="synthetic-key",
            _env_file=None,
        ),
        client=client,
    )

    sender.send(_message())

    assert client.calls[0][2]["ServerId"] == 12345


def test_development_mode_guards_socketlabs_before_provider_call() -> None:
    client = FakeHttpClient()
    sender = build_email_sender(
        Settings(
            email_delivery_mode="development",
            socketlabs_server_id="12345",
            socketlabs_injection_api_key="synthetic-key",
            _env_file=None,
        ),
        client=client,
    )

    with pytest.raises(EmailConfigurationError):
        sender.send(_message(to=("person@example.com",)))

    assert client.calls == []


@pytest.mark.parametrize(
    "mailbox",
    [
        "person@example.com",
        "person@sub.jeffo.net",
        "person@jeffo.net.example.com",
        "person@notjeffo.net",
        "person@sub.pentacoop.com",
        "person@pentacoop.com.example.com",
        "person@notpentacoop.com",
    ],
)
@pytest.mark.parametrize("recipient_field", ["to", "cc", "bcc"])
def test_development_sender_rejects_every_non_exact_recipient_domain(
    mailbox: str, recipient_field: str
) -> None:
    inner = CapturedEmailSender()
    sender = DevelopmentEmailSender(
        inner,
        sender="applications@jeffo.net",
        reply_to="membership@jeffo.net",
    )

    with pytest.raises(EmailConfigurationError):
        sender.send(_message(**{recipient_field: (mailbox,)}))

    assert inner.messages == []


@pytest.mark.parametrize("domain", ["jeffo.net", "pentacoop.com"])
def test_development_sender_prefixes_subject_and_allows_approved_domains(
    domain: str,
) -> None:
    inner = CapturedEmailSender()
    sender = DevelopmentEmailSender(
        inner,
        sender=f"Penta Dev <applications@{domain}>",
        reply_to=f"Membership <membership@{domain}>",
    )

    sender.send(_message(to=(f"Applicant <person@{domain.upper()}>",)))

    assert inner.messages[0].subject == "[Penta development] Return to your application"


def test_development_sender_rejects_header_injection() -> None:
    sender = DevelopmentEmailSender(
        CapturedEmailSender(),
        sender="applications@jeffo.net",
        reply_to="membership@jeffo.net",
    )

    with pytest.raises(EmailConfigurationError):
        sender.send(_message(to=("person@jeffo.net\r\nBcc: victim@example.com",)))


def test_development_sender_rejects_a_mixed_recipient_list_before_delivery() -> None:
    inner = CapturedEmailSender()
    sender = DevelopmentEmailSender(
        inner,
        sender="applications@pentacoop.com",
        reply_to="applications@pentacoop.com",
    )

    with pytest.raises(EmailConfigurationError):
        sender.send(
            _message(to=("safe@jeffo.net", "unsafe@example.com"))
        )

    assert inner.messages == []


@pytest.mark.parametrize("identity_field", ["sender", "reply_to"])
@pytest.mark.parametrize(
    "mailbox",
    [
        "applications@example.com",
        "applications@sub.jeffo.net",
        "applications@pentacoop.com.example.com",
        "applications@pentacoop.com\r\nBcc: victim@example.com",
    ],
)
def test_development_sender_rejects_unsafe_delivery_identities(
    identity_field: str, mailbox: str
) -> None:
    identities = {
        "sender": "applications@pentacoop.com",
        "reply_to": "applications@pentacoop.com",
    }
    identities[identity_field] = mailbox

    with pytest.raises(EmailConfigurationError):
        DevelopmentEmailSender(CapturedEmailSender(), **identities)
