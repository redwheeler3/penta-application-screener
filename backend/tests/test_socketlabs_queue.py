from datetime import UTC, datetime, timedelta

from app.api.email_delivery import (
    read_public_email_delivery_status,
    refresh_public_email_delivery_status,
)
from app.services.socketlabs_queue import (
    CachedSocketLabsQueueReader,
    SocketLabsQueueClient,
    SocketLabsQueueStatus,
)


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.payload


class FakeClient:
    def __init__(self, pages: list[dict]) -> None:
        self.pages = pages
        self.calls: list[dict] = []

    def get(self, _url: str, *, headers: dict, params: dict) -> FakeResponse:
        self.calls.append({"headers": headers, "params": dict(params)})
        return FakeResponse(self.pages[len(self.calls) - 1])


class CountingReader:
    def __init__(self, result: SocketLabsQueueStatus | None) -> None:
        self.result = result
        self.calls = 0

    def cached(self) -> SocketLabsQueueStatus | None:
        return self.result

    def fetch(self) -> SocketLabsQueueStatus | None:
        self.calls += 1
        return self.result


def _message(status: str, queued_time: str) -> dict:
    # Real reports include recipient addresses and other message metadata. The
    # reader deliberately projects only these two non-PII queue fields.
    return {
        "status": status,
        "queuedTime": queued_time,
        "to": "private@example.test",
        "subject": "Private subject",
    }


def test_queue_reader_aggregates_pending_messages_across_pages() -> None:
    client = FakeClient(
        [
            {
                "total": 3,
                "data": [
                    _message("Delivered", "2026-09-24T10:00:00Z"),
                    _message("Queued", "2026-09-24T10:05:00.1234567Z"),
                ],
            },
            {
                "total": 3,
                "data": [_message("Deferred", "2026-09-24T10:10:00Z")],
            },
        ]
    )
    reader = SocketLabsQueueClient(
        client,  # type: ignore[arg-type]
        base_url="https://api.socketlabs.test",
        server_id=123,
        api_key="secret",
    )

    status = reader.fetch()

    assert status is not None
    assert status.queued_count == 2
    assert status.oldest_queued_at == datetime(
        2026, 9, 24, 10, 5, 0, 123456, tzinfo=UTC
    )
    assert len(client.calls) == 2
    assert client.calls[1]["params"]["pageNumber"] == 1
    assert not hasattr(status, "to")
    assert not hasattr(status, "subject")


def test_delay_requires_ten_pending_messages() -> None:
    now = datetime.now(UTC)

    assert SocketLabsQueueStatus(now, 9, now - timedelta(days=1)).delayed is False
    assert SocketLabsQueueStatus(now, 10, now - timedelta(minutes=1)).delayed is True


def test_queue_reader_caches_success_and_failure() -> None:
    status = SocketLabsQueueStatus(datetime.now(UTC), 0, None)
    successful = CountingReader(status)
    cached_success = CachedSocketLabsQueueReader(successful)
    assert cached_success.cached() is None
    assert cached_success.fetch() is status
    assert cached_success.cached() is status
    assert cached_success.fetch() is status
    assert successful.calls == 1

    successful.result = None
    cached_success.cache_duration = timedelta(0)
    assert cached_success.fetch() is None
    assert cached_success.cached() is status

    unavailable = CountingReader(None)
    cached_failure = CachedSocketLabsQueueReader(unavailable)
    assert cached_failure.fetch() is None
    assert cached_failure.fetch() is None
    assert unavailable.calls == 1


def test_public_status_fails_open_without_exposing_queue_details() -> None:
    delayed = CountingReader(
        SocketLabsQueueStatus(
            retrieved_at=datetime.now(UTC),
            queued_count=10,
            oldest_queued_at=None,
        )
    )
    assert read_public_email_delivery_status(delayed).model_dump() == {
        "available": True,
        "delayed": True,
    }
    assert delayed.calls == 0
    assert refresh_public_email_delivery_status(delayed).model_dump() == {
        "available": True,
        "delayed": True
    }
    assert delayed.calls == 1

    unavailable = CountingReader(None)
    assert read_public_email_delivery_status(unavailable).model_dump() == {
        "available": False,
        "delayed": False
    }
