"""The run lease: serialize the expensive AI runs (Screen / Rank / score-current) across
members.

One fixed row (``RunLock`` id=1, seeded by migration). ``acquire_run_lock`` claims it with an
atomic conditional UPDATE — free, held-by-nobody, or a stale lease past the TTL — and returns
whether it won. The run stream releases it in a ``finally``; a crashed run that never releases
is reclaimed once its lease ages past ``LEASE_TTL``. No in-process lock is used because it
would not survive multiple web workers; the DB row is the single source of truth.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import case, select, update
from sqlalchemy.orm import Session

from app.core.time import as_utc
from app.db.models import RunLock

# The single lease row's fixed id (seeded by migration).
LOCK_ID = 1

# An expired lease can be reclaimed after a crashed run. Releases must identify the
# acquisition so an older run cannot clear a replacement lease for the same member.
LEASE_TTL = timedelta(minutes=15)


@dataclass(frozen=True)
class RunLease:
    user_id: int
    acquired_at: datetime


class RunLeaseLost(RuntimeError):
    """The run must stop because its acquisition no longer owns a live lease."""


def ensure_lock_row(db: Session) -> None:
    """Ensure the single free lease row exists (id=1). The migration seeds it in a real DB;
    this backs schema-only setups that don't run migrations (tests build via
    ``Base.metadata.create_all``). Idempotent."""
    if db.scalar(select(RunLock).where(RunLock.id == LOCK_ID)) is None:
        db.add(RunLock(id=LOCK_ID))
        db.commit()


def lock_run_state(db: Session) -> None:
    """Hold the lease row while an edit checks policy and commits; do not claim a run."""
    db.execute(update(RunLock).where(RunLock.id == LOCK_ID)
        .values(held_since=RunLock.held_since)
        .execution_options(synchronize_session=False))


def acquire_run_lock(
    db: Session, *, user_id: int, kind: str, now: datetime | None = None
) -> RunLease | None:
    """Return the claimed acquisition for ``kind``, or None when another run holds it.

    Atomic: a single conditional UPDATE claims the row only when it is free (no holder) or the
    current lease has aged past ``LEASE_TTL``. Under SQLite's single writer (and equally under
    Postgres) exactly one concurrent caller's UPDATE matches, so there is no check-then-set
    race. A None return means another run holds the lease — the caller should 409.
    """
    now = now or datetime.now(UTC)
    cutoff = now - LEASE_TTL
    result = db.execute(
        update(RunLock)
        .where(
            RunLock.id == LOCK_ID,
            (RunLock.holder_user_id.is_(None)) | (RunLock.renewed_at < cutoff),
        )
        .values(holder_user_id=user_id, kind=kind, held_since=now, renewed_at=now)
    )
    db.commit()
    return RunLease(user_id=user_id, acquired_at=now) if result.rowcount == 1 else None


def renew_run_lock(db: Session, lease: RunLease, *, now: datetime | None = None, commit: bool = True) -> bool:
    """Renew only a live acquisition; with commit=False, fence the caller's transaction.

    This conditional write holds SQLite's writer through the result commit, so a
    replacement cannot take ownership between verification and persistence.
    """
    now = now or datetime.now(UTC)
    with db.no_autoflush:
        result = db.execute(update(RunLock).where(
            RunLock.id == LOCK_ID, RunLock.holder_user_id == lease.user_id,
            RunLock.held_since == lease.acquired_at, RunLock.renewed_at >= now - LEASE_TTL,
        ).values(renewed_at=case((RunLock.renewed_at > now, RunLock.renewed_at), else_=now))
            .execution_options(synchronize_session=False))
    if commit:
        db.commit()
    return result.rowcount == 1


def release_run_lock(db: Session, lease: RunLease) -> None:
    """Release only this acquisition, even if a replacement belongs to the same user."""
    db.execute(
        update(RunLock)
        .where(
            RunLock.id == LOCK_ID,
            RunLock.holder_user_id == lease.user_id,
            RunLock.held_since == lease.acquired_at,
        )
        .values(holder_user_id=None, kind=None, held_since=None, renewed_at=None)
    )
    db.commit()


def rank_run_in_progress(db: Session, *, now: datetime | None = None) -> bool:
    """Whether a full **rank** run currently holds the lease (a live, non-stale lease of kind
    'rank'). A rank snapshots the committee kept-list once at the start of discovery and then
    creates a NEW analysis; a member's tier/seed edit made after that snapshot would neither
    reach this run NOR survive it (the edit targets the old analysis, which the run supersedes),
    so an axis dragged out of Ignore could silently vanish. Tier/seed saves are blocked while
    this is true. Only 'rank' — screen/score-current hold the lease too but touch no dimensions,
    so editing during them is safe. TTL-expired leases are ignored (a crashed run frees it)."""
    lease = db.scalar(select(RunLock).where(RunLock.id == LOCK_ID)
        .execution_options(populate_existing=True))
    if lease is None or lease.kind != "rank" or lease.renewed_at is None:
        return False
    now = now or datetime.now(UTC)
    return as_utc(lease.renewed_at) >= now - LEASE_TTL
