"""Small in-process limiter for low-volume unauthenticated write endpoints."""

from collections import OrderedDict, deque
from datetime import UTC, datetime, timedelta
from threading import Lock


class PublicRateLimiter:
    def __init__(
        self, *, limit: int, window: timedelta, max_keys: int = 10_000
    ) -> None:
        if limit < 1 or window <= timedelta(0) or max_keys < 1:
            raise ValueError("Limiter limits and window must be positive")
        self.limit = limit
        self.window = window
        self.max_keys = max_keys
        # Ordered by the latest accepted attempt, so expired buckets are at the front.
        self._attempts: OrderedDict[str, deque[datetime]] = OrderedDict()
        self._last_check: datetime | None = None
        self._lock = Lock()

    def allow(self, key: str, *, now: datetime | None = None) -> bool:
        current = now or datetime.now(UTC)
        with self._lock:
            # A wall-clock correction must not reorder buckets or reopen quotas.
            current = max(current, self._last_check or current)
            self._last_check = current
            cutoff = current - self.window
            # Bound cleanup per request; repeated traffic amortizes expiry work.
            for _ in range(128):
                if not self._attempts:
                    break
                oldest_key, oldest = next(iter(self._attempts.items()))
                if oldest[-1] > cutoff:
                    break
                del self._attempts[oldest_key]
            attempts = self._attempts.get(key)
            if attempts is None:
                # Preserve live quotas under cardinality pressure rather than
                # evicting them and allowing a caller to start over.
                if len(self._attempts) >= self.max_keys:
                    return False
                attempts = deque()
                self._attempts[key] = attempts
            while attempts and attempts[0] <= cutoff:
                attempts.popleft()
            if len(attempts) >= self.limit:
                return False
            attempts.append(current)
            self._attempts.move_to_end(key)
            return True

    def clear(self) -> None:
        with self._lock:
            self._attempts.clear()
            self._last_check = None
