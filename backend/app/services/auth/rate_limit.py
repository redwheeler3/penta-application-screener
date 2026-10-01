"""Small in-process limiter for low-volume unauthenticated write endpoints."""

from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta
from threading import Lock


class PublicRateLimiter:
    def __init__(self, *, limit: int, window: timedelta) -> None:
        self.limit = limit
        self.window = window
        self._attempts: dict[str, deque[datetime]] = defaultdict(deque)
        self._lock = Lock()

    def allow(self, key: str, *, now: datetime | None = None) -> bool:
        current = now or datetime.now(UTC)
        cutoff = current - self.window
        with self._lock:
            attempts = self._attempts[key]
            while attempts and attempts[0] <= cutoff:
                attempts.popleft()
            if len(attempts) >= self.limit:
                return False
            attempts.append(current)
            return True

    def clear(self) -> None:
        with self._lock:
            self._attempts.clear()
