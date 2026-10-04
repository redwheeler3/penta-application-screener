"""The run lease serializing AI runs across members."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.time import as_utc
from app.db.models import Base, RunLock, User, UserRole
from app.services.run_lock import (
    LEASE_TTL,
    RunLease,
    acquire_run_lock,
    ensure_lock_row,
    rank_run_in_progress,
    release_run_lock,
    renew_run_lock,
)


def make_db() -> Session:
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    ensure_lock_row(db)
    for i in (1, 2):
        db.add(User(email=f"u{i}@x.com", display_name=f"U{i}", role=UserRole.MEMBER, is_active=True))
    db.commit()
    return db


def test_acquire_then_contended() -> None:
    """One holder wins; a second run while it's held loses (would 409)."""
    db = make_db()
    assert acquire_run_lock(db, user_id=1, kind="rank") is not None
    assert acquire_run_lock(db, user_id=2, kind="screen") is None  # still held by user 1


def test_renewal_preserves_acquisition_and_expires_from_last_activity() -> None:
    db = make_db()
    now = datetime.now(UTC)
    lease = acquire_run_lock(db, user_id=1, kind="rank", now=now)
    renewed_at = now + timedelta(minutes=14)
    assert renew_run_lock(db, lease, now=renewed_at)
    assert renew_run_lock(db, lease, now=renewed_at - timedelta(seconds=1))
    assert as_utc(db.get(RunLock, 1, populate_existing=True).renewed_at) == renewed_at
    assert rank_run_in_progress(db, now=now + timedelta(minutes=17))
    assert acquire_run_lock(db, user_id=2, kind="screen", now=now + timedelta(minutes=17)) is None
    replacement = acquire_run_lock(db, user_id=2, kind="screen", now=renewed_at + LEASE_TTL + timedelta(seconds=1))
    assert replacement is not None
    assert not renew_run_lock(db, lease, now=renewed_at + LEASE_TTL + timedelta(seconds=2))
    release_run_lock(db, lease)
    assert acquire_run_lock(db, user_id=1, kind="screen", now=renewed_at + LEASE_TTL + timedelta(seconds=2)) is None


def test_release_frees_the_lease() -> None:
    db = make_db()
    lease = acquire_run_lock(db, user_id=1, kind="rank")
    release_run_lock(db, lease)
    assert acquire_run_lock(db, user_id=2, kind="screen") is not None  # free again


def test_release_is_holder_guarded() -> None:
    """A run that already lost its lease (e.g. to a TTL steal) can't clear a newer holder."""
    db = make_db()
    lease = acquire_run_lock(db, user_id=1, kind="rank")
    release_run_lock(db, RunLease(user_id=2, acquired_at=lease.acquired_at))  # user 2 isn't the holder — no-op
    assert acquire_run_lock(db, user_id=2, kind="screen") is None  # user 1 still holds it


def test_stale_lease_is_stealable_after_ttl() -> None:
    """A lease older than the TTL (a crashed run that never released) is reclaimable."""
    db = make_db()
    # Claim as if it happened well over the TTL ago.
    stale = datetime.now(UTC) - LEASE_TTL - timedelta(minutes=1)
    assert acquire_run_lock(db, user_id=1, kind="rank", now=stale) is not None
    # A fresh acquire now steals the abandoned lease.
    assert acquire_run_lock(db, user_id=2, kind="screen") is not None


def test_fresh_lease_is_not_stealable() -> None:
    """A lease within the TTL is a live run — not stealable."""
    db = make_db()
    just_now = datetime.now(UTC) - timedelta(minutes=1)  # well within the 15m TTL
    assert acquire_run_lock(db, user_id=1, kind="rank", now=just_now) is not None
    assert acquire_run_lock(db, user_id=2, kind="screen") is None


def test_expired_run_cannot_release_a_replacement_for_the_same_member() -> None:
    db = make_db()
    now = datetime.now(UTC)
    original = acquire_run_lock(db, user_id=1, kind="rank", now=now - LEASE_TTL - timedelta(seconds=1))
    replacement = acquire_run_lock(db, user_id=1, kind="rank", now=now)
    assert original is not None
    assert replacement is not None
    release_run_lock(db, original)
    assert acquire_run_lock(db, user_id=2, kind="screen", now=now) is None
    release_run_lock(db, replacement)
    assert acquire_run_lock(db, user_id=2, kind="screen", now=now) is not None


def test_rank_run_in_progress_only_for_a_live_rank_lease() -> None:
    """The tier/seed-edit block keys on a LIVE rank lease specifically."""
    db = make_db()
    assert rank_run_in_progress(db) is False  # free lease

    # A screen or score-current run holds the lease but touches no dimensions — editing is safe.
    lease = acquire_run_lock(db, user_id=1, kind="screen")
    assert rank_run_in_progress(db) is False
    release_run_lock(db, lease)

    lease = acquire_run_lock(db, user_id=1, kind="rank_scores")
    assert rank_run_in_progress(db) is False
    release_run_lock(db, lease)

    # A full rank IS the dangerous case (snapshots kept-list, supersedes the analysis).
    lease = acquire_run_lock(db, user_id=1, kind="rank")
    assert rank_run_in_progress(db) is True
    release_run_lock(db, lease)
    assert rank_run_in_progress(db) is False


def test_stale_rank_lease_does_not_block() -> None:
    """A crashed rank that never released (lease past the TTL) must not wedge editing forever."""
    db = make_db()
    stale = datetime.now(UTC) - LEASE_TTL - timedelta(minutes=1)
    acquire_run_lock(db, user_id=1, kind="rank", now=stale)
    assert rank_run_in_progress(db) is False  # TTL-expired → ignored
