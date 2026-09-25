"""Aggregate SocketLabs' provider-side queue without retaining recipient data."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from threading import Lock
from typing import Protocol

import httpx

from app.core.config import Settings, get_settings
from app.core.time import as_utc, pacific_today

QUEUE_TIMEOUT_SECONDS = 10.0
QUEUE_CACHE_DURATION = timedelta(minutes=5)
QUEUE_REPORT_LOOKBACK_DAYS = 2
QUEUE_REPORT_PAGE_SIZE = 1000
DELAYED_QUEUE_COUNT = 10
PENDING_STATUSES = frozenset({"queued", "deferred", "processing"})


@dataclass(frozen=True)
class SocketLabsQueueStatus:
    retrieved_at: datetime
    queued_count: int
    oldest_queued_at: datetime | None

    @property
    def delayed(self) -> bool:
        return self.queued_count >= DELAYED_QUEUE_COUNT


class SocketLabsQueueReader(Protocol):
    def fetch(self) -> SocketLabsQueueStatus | None: ...


class UnavailableSocketLabsQueueReader:
    def fetch(self) -> None:
        return None


class SocketLabsQueueClient:
    def __init__(
        self,
        client: httpx.Client,
        *,
        base_url: str,
        server_id: int,
        api_key: str,
    ) -> None:
        self.client = client
        self.url = f"{base_url.rstrip('/')}/v2/servers/{server_id}/reports/message/"
        self.api_key = api_key

    def fetch(self) -> SocketLabsQueueStatus | None:
        now = datetime.now(UTC)
        today = pacific_today(now=now)
        params: dict[str, str | int] = {
            "pageSize": QUEUE_REPORT_PAGE_SIZE,
            "pageNumber": 0,
            "sortField": "queuedTime",
            "sortDirection": "asc",
            "startDate": (today - timedelta(days=QUEUE_REPORT_LOOKBACK_DAYS)).isoformat(),
            "endDate": today.isoformat(),
        }
        try:
            seen = 0
            queued_count = 0
            oldest_queued_at: datetime | None = None
            while True:
                response = self.client.get(
                    self.url,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    params=params,
                )
                response.raise_for_status()
                payload = response.json()
                page = payload["data"]
                total = int(payload["total"])
                if not isinstance(page, list):
                    return None
                seen += len(page)
                for message in page:
                    if not isinstance(message, dict) or not _is_pending(message):
                        continue
                    queued_count += 1
                    queued_at = _queued_at(message)
                    if queued_at is not None and (
                        oldest_queued_at is None or queued_at < oldest_queued_at
                    ):
                        oldest_queued_at = queued_at
                if seen >= total or not page:
                    break
                params["pageNumber"] = int(params["pageNumber"]) + 1

            return SocketLabsQueueStatus(
                retrieved_at=now,
                queued_count=queued_count,
                oldest_queued_at=oldest_queued_at,
            )
        except (httpx.HTTPError, KeyError, TypeError, ValueError):
            return None


class CachedSocketLabsQueueReader:
    def __init__(
        self,
        inner: SocketLabsQueueReader,
        *,
        cache_duration: timedelta = QUEUE_CACHE_DURATION,
    ) -> None:
        self.inner = inner
        self.cache_duration = cache_duration
        self._lock = Lock()
        self._cached_at: datetime | None = None
        self._cached: SocketLabsQueueStatus | None = None

    def fetch(self) -> SocketLabsQueueStatus | None:
        now = datetime.now(UTC)
        if self._is_fresh(now):
            return self._cached
        with self._lock:
            now = datetime.now(UTC)
            if self._is_fresh(now):
                return self._cached
            self._cached = self.inner.fetch()
            self._cached_at = now
            return self._cached

    def _is_fresh(self, now: datetime) -> bool:
        return (
            self._cached_at is not None
            and self._cached_at > now - self.cache_duration
        )


def _is_pending(message: dict[str, object]) -> bool:
    status = str(message.get("status", "")).strip().lower()
    return status in PENDING_STATUSES


def _queued_at(message: dict[str, object]) -> datetime | None:
    value = message.get("queuedTime")
    if not isinstance(value, str) or not value:
        return None
    return as_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))


def build_socketlabs_queue_reader(settings: Settings) -> SocketLabsQueueReader:
    if not settings.email_delivery_enabled:
        return UnavailableSocketLabsQueueReader()
    try:
        server_id = int(settings.socketlabs_server_id)
    except ValueError:
        return UnavailableSocketLabsQueueReader()
    if server_id <= 0 or not settings.socketlabs_injection_api_key:
        return UnavailableSocketLabsQueueReader()
    return CachedSocketLabsQueueReader(
        SocketLabsQueueClient(
            httpx.Client(timeout=QUEUE_TIMEOUT_SECONDS),
            base_url=settings.socketlabs_api_base,
            server_id=server_id,
            api_key=settings.socketlabs_injection_api_key,
        )
    )


@lru_cache
def get_socketlabs_queue_reader() -> SocketLabsQueueReader:
    return build_socketlabs_queue_reader(get_settings())
