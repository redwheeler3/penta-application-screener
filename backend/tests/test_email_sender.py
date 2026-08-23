import pytest

from app.core.config import Settings
from app.services.email_sender import (
    CapturedEmailSender,
    DevelopmentEmailSender,
    EmailConfigurationError,
    OutboundEmail,
    SesEmailSender,
    build_email_sender,
)


class FakeSesClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def send_email(self, **kwargs):
        self.calls.append(kwargs)
        return {"MessageId": "ses-message-1"}


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


def test_capture_mode_is_the_default_and_performs_no_provider_call() -> None:
    sender = build_email_sender(Settings(_env_file=None))

    assert isinstance(sender, CapturedEmailSender)
    assert sender.send(_message()) == "captured-1"
    assert sender.messages == [_message()]


@pytest.mark.parametrize(
    "mailbox",
    [
        "person@example.com",
        "person@sub.jeffo.net",
        "person@jeffo.net.example.com",
        "person@notjeffo.net",
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


def test_development_sender_prefixes_subject_and_allows_display_names() -> None:
    inner = CapturedEmailSender()
    sender = DevelopmentEmailSender(
        inner,
        sender="Penta Dev <applications@jeffo.net>",
        reply_to="Membership <membership@jeffo.net>",
    )

    sender.send(_message(to=("Applicant <person@JEFFO.NET>",)))

    assert inner.messages[0].subject == "[Penta development] Return to your application"


def test_development_sender_rejects_header_injection() -> None:
    sender = DevelopmentEmailSender(
        CapturedEmailSender(),
        sender="applications@jeffo.net",
        reply_to="membership@jeffo.net",
    )

    with pytest.raises(EmailConfigurationError):
        sender.send(_message(to=("person@jeffo.net\r\nBcc: victim@example.com",)))


def test_ses_adapter_maps_provider_neutral_message() -> None:
    client = FakeSesClient()
    sender = SesEmailSender(
        client,
        sender="Penta <applications@pentacoop.com>",
        reply_to="membership@pentacoop.com",
    )

    message_id = sender.send(_message(to=("applicant@example.com",)))

    assert message_id == "ses-message-1"
    assert client.calls[0]["Source"] == "applications@pentacoop.com"
    assert client.calls[0]["Destination"]["ToAddresses"] == ["applicant@example.com"]
    assert client.calls[0]["Message"]["Body"]["Text"]["Data"] == "Synthetic transactional email."


def test_live_mode_requires_sender_and_reply_to() -> None:
    with pytest.raises(EmailConfigurationError):
        build_email_sender(
            Settings(email_delivery_mode="production_ses", _env_file=None),
            ses_client=FakeSesClient(),
        )


def test_production_mode_requires_fixed_penta_sender() -> None:
    with pytest.raises(EmailConfigurationError):
        build_email_sender(
            Settings(
                email_delivery_mode="production_ses",
                email_sender="wrong@pentacoop.com",
                email_reply_to="membership@pentacoop.com",
                _env_file=None,
            ),
            ses_client=FakeSesClient(),
        )
