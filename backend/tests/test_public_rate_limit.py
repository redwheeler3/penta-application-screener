from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

from app.services.auth.rate_limit import PublicRateLimiter


def test_expiry_reclaims_inactive_buckets_in_bounded_batches() -> None:
    limiter = PublicRateLimiter(limit=2, window=timedelta(minutes=15), max_keys=1_000)
    start = datetime(2026, 10, 4, tzinfo=UTC)
    for index in range(1_000):
        assert limiter.allow(str(index), now=start)
    later = start + timedelta(days=1)
    assert limiter.allow("fresh", now=later)
    assert len(limiter._attempts) == 873
    for _ in range(8):
        limiter.allow("fresh", now=later)
    assert list(limiter._attempts) == ["fresh"]


def test_capacity_never_evicts_a_live_quota() -> None:
    limiter = PublicRateLimiter(limit=1, window=timedelta(minutes=15), max_keys=2)
    start = datetime(2026, 10, 4, tzinfo=UTC)
    assert limiter.allow("a", now=start)
    assert limiter.allow("b", now=start)
    assert not limiter.allow("c", now=start)
    assert not limiter.allow("a", now=start)
    assert limiter.allow("c", now=start + timedelta(minutes=15))


def test_clock_reversal_does_not_reset_or_reorder_active_quotas() -> None:
    limiter = PublicRateLimiter(limit=2, window=timedelta(minutes=15))
    start = datetime(2026, 10, 4, tzinfo=UTC)
    assert limiter.allow("a", now=start)
    assert limiter.allow("b", now=start + timedelta(minutes=1))
    assert limiter.allow("a", now=start - timedelta(minutes=1))
    assert not limiter.allow("a", now=start)
    assert limiter.allow("c", now=start + timedelta(minutes=16))
    assert list(limiter._attempts) == ["c"]


def test_concurrent_attempts_share_one_quota() -> None:
    limiter = PublicRateLimiter(limit=10, window=timedelta(minutes=15))
    with ThreadPoolExecutor(max_workers=8) as workers:
        results = list(workers.map(lambda _: limiter.allow("same"), range(100)))
    assert sum(results) == 10
