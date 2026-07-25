"""The run lease serializing AI runs across members (M16 concurrency hardening)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base, User, UserRole
from app.services.run_lock import (
    LEASE_TTL,
    acquire_run_lock,
    ensure_lock_row,
    release_run_lock,
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
    assert acquire_run_lock(db, user_id=1, kind="rank") is True
    assert acquire_run_lock(db, user_id=2, kind="screen") is False  # still held by user 1


def test_release_frees_the_lease() -> None:
    db = make_db()
    acquire_run_lock(db, user_id=1, kind="rank")
    release_run_lock(db, user_id=1)
    assert acquire_run_lock(db, user_id=2, kind="screen") is True  # free again


def test_release_is_holder_guarded() -> None:
    """A run that already lost its lease (e.g. to a TTL steal) can't clear a newer holder."""
    db = make_db()
    acquire_run_lock(db, user_id=1, kind="rank")
    release_run_lock(db, user_id=2)  # user 2 isn't the holder — no-op
    assert acquire_run_lock(db, user_id=2, kind="screen") is False  # user 1 still holds it


def test_stale_lease_is_stealable_after_ttl() -> None:
    """A lease older than the TTL (a crashed run that never released) is reclaimable."""
    db = make_db()
    # Claim as if it happened well over the TTL ago.
    stale = datetime.now(UTC) - LEASE_TTL - timedelta(minutes=1)
    assert acquire_run_lock(db, user_id=1, kind="rank", now=stale) is True
    # A fresh acquire now steals the abandoned lease.
    assert acquire_run_lock(db, user_id=2, kind="screen") is True


def test_fresh_lease_is_not_stealable() -> None:
    """A lease within the TTL is a live run — not stealable."""
    db = make_db()
    just_now = datetime.now(UTC) - timedelta(minutes=1)  # well within the 15m TTL
    assert acquire_run_lock(db, user_id=1, kind="rank", now=just_now) is True
    assert acquire_run_lock(db, user_id=2, kind="screen") is False
