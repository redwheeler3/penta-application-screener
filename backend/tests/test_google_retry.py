from types import SimpleNamespace

import pytest
from googleapiclient.errors import HttpError

from app.services.google_retry import GOOGLE_RETRY_DELAY_SECONDS, retry_google_request


def _http_error(status: int) -> HttpError:
    return HttpError(SimpleNamespace(status=status, reason="test"), b"error")


def test_retry_google_request_retries_a_timeout_once(monkeypatch) -> None:
    calls = 0
    sleeps: list[float] = []

    def operation() -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise TimeoutError("temporary outage")
        return "done"

    monkeypatch.setattr("app.services.google_retry.time.sleep", sleeps.append)

    assert retry_google_request(operation) == "done"
    assert calls == 2
    assert sleeps == [GOOGLE_RETRY_DELAY_SECONDS]


def test_retry_google_request_retries_rate_limit_once(monkeypatch) -> None:
    calls = 0

    def operation() -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise _http_error(429)
        return "done"

    monkeypatch.setattr("app.services.google_retry.time.sleep", lambda _: None)

    assert retry_google_request(operation) == "done"
    assert calls == 2


def test_retry_google_request_does_not_retry_permission_errors(monkeypatch) -> None:
    monkeypatch.setattr("app.services.google_retry.time.sleep", lambda _: pytest.fail("should not sleep"))

    def operation() -> None:
        raise _http_error(403)

    with pytest.raises(HttpError):
        retry_google_request(operation)
