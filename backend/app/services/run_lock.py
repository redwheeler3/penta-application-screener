"""The run lease: serialize the expensive AI runs (Screen / Rank / score-current) across
members.

One fixed row (``RunLock`` id=1, seeded by migration). ``acquire_run_lock`` claims it with an
atomic conditional UPDATE — free, held-by-nobody, or a stale lease past the TTL — and returns
whether it won. The run stream releases it in a ``finally``; a crashed run that never releases
is reclaimed once its lease ages past ``LEASE_TTL``. No in-process lock is used because it
would not survive multiple web workers; the DB row is the single source of truth.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.models import RunLock

# The single lease row's fixed id (seeded by migration).
LOCK_ID = 1

# A lease older than this is presumed dead (its run crashed without releasing) and may be
# stolen. Comfortably longer than any real run — a full Rank over the pool is minutes, not
# quarter-hours — so this only ever reclaims a genuinely abandoned lease, never a live run.
LEASE_TTL = timedelta(minutes=15)


def ensure_lock_row(db: Session) -> None:
    """Ensure the single free lease row exists (id=1). The migration seeds it in a real DB;
    this backs schema-only setups that don't run migrations (tests build via
    ``Base.metadata.create_all``). Idempotent."""
    if db.scalar(select(RunLock).where(RunLock.id == LOCK_ID)) is None:
        db.add(RunLock(id=LOCK_ID))
        db.commit()


def acquire_run_lock(db: Session, *, user_id: int, kind: str, now: datetime | None = None) -> bool:
    """Try to claim the run lease for ``kind`` on behalf of ``user_id``. Returns True if won.

    Atomic: a single conditional UPDATE claims the row only when it is free (no holder) or the
    current lease has aged past ``LEASE_TTL``. Under SQLite's single writer (and equally under
    Postgres) exactly one concurrent caller's UPDATE matches, so there is no check-then-set
    race. A False return means another run is genuinely in flight — the caller should 409.
    """
    now = now or datetime.now(UTC)
    cutoff = now - LEASE_TTL
    result = db.execute(
        update(RunLock)
        .where(
            RunLock.id == LOCK_ID,
            (RunLock.holder_user_id.is_(None)) | (RunLock.held_since < cutoff),
        )
        .values(holder_user_id=user_id, kind=kind, held_since=now)
    )
    db.commit()
    return result.rowcount == 1


def release_run_lock(db: Session, *, user_id: int) -> None:
    """Release the lease if this user holds it (no-op otherwise). Guarded by holder so a run
    that already lost its lease to a TTL steal can't clear a newer holder's claim."""
    db.execute(
        update(RunLock)
        .where(RunLock.id == LOCK_ID, RunLock.holder_user_id == user_id)
        .values(holder_user_id=None, kind=None, held_since=None)
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
    lease = db.scalar(select(RunLock).where(RunLock.id == LOCK_ID))
    if lease is None or lease.kind != "rank" or lease.held_since is None:
        return False
    now = now or datetime.now(UTC)
    # SQLite's DateTime(timezone=True) round-trips as a naive datetime, so normalize to UTC-
    # aware before comparing (the acquire path sidesteps this by comparing DB-side in SQL).
    held_since = lease.held_since
    if held_since.tzinfo is None:
        held_since = held_since.replace(tzinfo=UTC)
    return held_since >= now - LEASE_TTL
