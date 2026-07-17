"""Safe SQLite backups — a transactionally consistent snapshot of the local DB.

Why not ``cp``: copying a live SQLite file can capture a torn write (a snapshot mid-
transaction is corrupt). ``VACUUM INTO`` produces a consistent, compact standalone copy
even while the DB is being written, so it is the correct primitive for a hot backup.

Backups land in ``backend/data/backups/`` (gitignored under the ``backend/data/*`` rule —
they hold real applicant PII and must never be committed). Filenames are timestamped and
tagged so a restore can pick the right one; ``prune`` keeps the newest N.

Used by both the manual CLI (``python -m app.services.backup``) and the automatic
post-Rank snapshot (see ``ranking.py``), so the snapshot logic lives in one place.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.db.session import engine as default_engine

# Keep this many most-recent backups; older ones are pruned. Generous — a snapshot is a
# few MB and these are the only durable record of a run's (expensive, non-deterministic)
# output once the live DB moves on.
DEFAULT_KEEP = 50

_TS_FMT = "%Y%m%d_%H%M%S"
# tag is a short human label ("rank", "manual", "pre-restore"); constrained so it can't
# inject path separators into the filename.
_TAG_RE = re.compile(r"[^a-z0-9-]+")


def _sqlite_path(engine: Engine) -> Path:
    """The on-disk path of ``engine``'s SQLite database. Raises if the engine is not a
    FILE-BACKED SQLite DB — backups are a local-SQLite convenience, not a prod strategy,
    and an in-memory DB (``:memory:``, the test engine) has nothing on disk to copy.

    Rejecting ``:memory:`` explicitly matters: ``Path(":memory:").resolve()`` would
    otherwise resolve to ``<cwd>/:memory:``, so ``backups_dir`` would land under the
    process CWD (``backend/``) and every rank test's auto-snapshot would dump a real
    backup there. The guard turns that into a clean skip (the auto-snapshot caller
    treats it as best-effort)."""
    url = engine.url
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        raise RuntimeError("DB backups require a file-backed local SQLite database.")
    return Path(url.database).resolve()


# The engine to snapshot. Passed explicitly by request-path callers (via the session that
# is in scope, so a test's overridden engine is honored and its backups land beside its
# own temp DB) and defaulted to the app engine for CLI use.
def _resolve(engine: Engine | None) -> Engine:
    return engine or default_engine


def backups_dir(engine: Engine | None = None) -> Path:
    """``<db-dir>/backups`` for the given engine's DB, created on demand."""
    d = _sqlite_path(_resolve(engine)).parent / "backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


def create_backup(*, engine: Engine | None = None, tag: str = "manual",
                   timestamp: datetime | None = None) -> Path:
    """Write a consistent snapshot and return its path. ``tag`` labels why it was taken;
    ``timestamp`` is injectable for tests (real callers pass None → now)."""
    eng = _resolve(engine)
    ts = (timestamp or datetime.now()).strftime(_TS_FMT)
    safe_tag = _TAG_RE.sub("-", tag.lower()).strip("-") or "backup"
    dest = backups_dir(eng) / f"penta_{ts}_{safe_tag}.db"
    # VACUUM INTO needs the target not to exist; the timestamp makes collisions unlikely,
    # but guard anyway rather than let SQLite error on a re-run within the same second.
    n = 1
    base = dest
    while dest.exists():
        dest = base.with_name(f"{base.stem}-{n}{base.suffix}")
        n += 1
    # VACUUM INTO takes a string literal path — quote single quotes defensively.
    literal = str(dest).replace("'", "''")
    with eng.connect() as conn:
        conn.execute(text(f"VACUUM INTO '{literal}'"))
    return dest


def list_backups(engine: Engine | None = None) -> list[Path]:
    """All backup files, newest first (by filename, which sorts by timestamp)."""
    return sorted(backups_dir(engine).glob("penta_*.db"), reverse=True)


def prune(keep: int = DEFAULT_KEEP, *, engine: Engine | None = None) -> list[Path]:
    """Delete all but the newest ``keep`` backups. Returns the deleted paths."""
    removed = list_backups(engine)[keep:]
    for p in removed:
        p.unlink()
    return removed


def create_and_prune(*, engine: Engine | None = None, tag: str = "manual",
                     keep: int = DEFAULT_KEEP) -> Path:
    """Snapshot then prune — the one call both the CLI and the auto-snapshot use."""
    eng = _resolve(engine)
    dest = create_backup(engine=eng, tag=tag)
    prune(keep=keep, engine=eng)
    return dest


def create_from_session(session: Session, *, tag: str, keep: int = DEFAULT_KEEP) -> Path | None:
    """Snapshot the DB the given ``session`` is bound to, or return None if that DB isn't
    file-backed (nothing to snapshot). Used by the request path (the auto post-Rank
    snapshot) so it honors a test's overridden engine instead of the global — otherwise
    tests would back up the real DB. bind is an Engine for our sessionmakers.

    A test binds an in-memory engine (``:memory:``); there's nothing on disk to copy, so
    this is a clean no-op (None), NOT an error — the auto-snapshot shouldn't fire, and
    shouldn't need the caller's try/except to swallow a raise for the normal test path."""
    bind = session.get_bind()
    eng = bind if isinstance(bind, Engine) else default_engine
    if not _is_file_backed(eng):
        return None
    return create_and_prune(engine=eng, tag=tag, keep=keep)


def _is_file_backed(engine: Engine) -> bool:
    """True when ``engine`` is a file-backed SQLite DB (so a backup is meaningful)."""
    url = engine.url
    return url.get_backend_name() == "sqlite" and bool(url.database) and url.database != ":memory:"


def restore_backup(source: Path, *, engine: Engine | None = None) -> Path:
    """Replace the live DB with ``source`` (a backup file), returning the DB path.

    Safety: snapshots the CURRENT live DB first (tag ``pre-restore``) so a mistaken
    restore is itself reversible — the very failure mode that motivated backups. Verifies
    ``source`` passes an integrity check before overwriting, so a corrupt backup can't
    clobber a good DB. The caller (CLI) is responsible for user confirmation."""
    import shutil
    import sqlite3

    eng = _resolve(engine)
    source = source.resolve()
    if not source.exists():
        raise FileNotFoundError(f"Backup not found: {source}")
    # Integrity-check the backup before trusting it over the live DB.
    with sqlite3.connect(str(source)) as conn:
        result = conn.execute("PRAGMA integrity_check").fetchone()
    if not result or result[0] != "ok":
        raise RuntimeError(f"Backup failed integrity check ({result}): {source}")

    db_path = _sqlite_path(eng)
    if db_path.exists():
        create_backup(engine=eng, tag="pre-restore")  # recoverable after the restore
    shutil.copy2(source, db_path)
    return db_path


def main() -> None:
    dest = create_and_prune(tag="manual")
    kept = list_backups()
    size_mb = dest.stat().st_size / 1_000_000
    print(f"Backup written: {dest}  ({size_mb:.1f} MB)")
    print(f"{len(kept)} backup(s) retained in {backups_dir()}")


if __name__ == "__main__":
    main()
