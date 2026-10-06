"""Safe SQLite backups — a transactionally consistent snapshot of the local DB.

Why not ``cp``: copying a live SQLite file can capture a torn write (a snapshot mid-
transaction is corrupt). ``VACUUM INTO`` produces a consistent, compact standalone copy
even while the DB is being written, so it is the correct primitive for a hot backup.

Backups land in ``backend/data/backups/`` (gitignored under the ``backend/data/*`` rule —
they hold real applicant PII and must never be committed). Filenames are timestamped and
tagged so a restore can pick the right one; ``prune`` keeps the newest N.

The service, its manual CLI (``python -m app.services.backup``), and the root backup/restore
scripts provide explicit local recovery points.
"""

from __future__ import annotations

import argparse
import re
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile

from alembic.config import Config
from sqlalchemy import Engine, create_engine, text, update
from sqlalchemy.orm import Session

from alembic import command
from app.core.time import as_utc
from app.db.models import (
    RECORD_ID_FLOOR,
    ApplicantDraft,
    Application,
    BrowserSession,
    DailyMaintenanceRun,
    EmailDelivery,
    EmailDeliveryState,
    MagicLinkToken,
    RunLock,
)
from app.db.session import engine as default_engine
from app.services.applications.purge import erase_application, erase_draft
from app.services.applications.result_retention import prune_unowned_results

# Keep this many most-recent backups; older ones are pruned. A snapshot is a few MB and
# 20 explicit recovery points are ample without the directory creeping toward a GB.
DEFAULT_KEEP = 20

_TS_FMT = "%Y%m%d_%H%M%S"
# tag is a short human label ("rank", "manual", "pre-restore"); constrained so it can't
# inject path separators into the filename.
_TAG_RE = re.compile(r"[^a-z0-9-]+")

def _sqlite_path(engine: Engine) -> Path:
    """The on-disk path of ``engine``'s SQLite database. Raises if the engine is not a
    FILE-BACKED SQLite DB — backups are a local-SQLite convenience, not a prod strategy,
    and an in-memory DB (``:memory:``, the test engine) has nothing on disk to copy.

    Rejecting ``:memory:`` explicitly matters: ``Path(":memory:").resolve()`` would
    otherwise resolve to ``<cwd>/:memory:``, so ``backups_dir`` would target an unrelated
    directory instead of a real database."""
    url = engine.url
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        raise RuntimeError("DB backups require a file-backed local SQLite database.")
    return Path(url.database).resolve()


# The engine to snapshot, passed explicitly by tests and defaulted for CLI use.
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
    """Newest timestamp first, with creation order resolving same-second snapshots.

    Tags and collision suffixes are labels, not chronological sort keys. File mtime
    records snapshot completion; the numeric suffix breaks ties on coarse filesystems.
    """
    def order(path: Path) -> tuple[str, int, int]:
        suffix = re.search(r"-(\d+)\.db$", path.name)
        return path.name[6:21], path.stat().st_mtime_ns, int(suffix[1]) if suffix else 0

    return sorted(backups_dir(engine).glob("penta_*.db"), key=order, reverse=True)


def prune(keep: int = DEFAULT_KEEP, *, engine: Engine | None = None,
          preserve: Path | None = None) -> list[Path]:
    """Delete all but the newest ``keep`` backups. Returns the deleted paths."""
    if keep < 0 or (preserve is not None and keep < 1):
        raise ValueError("Retention must keep the new recovery point and cannot be negative.")
    candidates = [path for path in list_backups(engine) if path != preserve]
    removed = candidates[keep - int(preserve is not None):]
    for p in removed:
        p.unlink()
    return removed


def create_and_prune(*, engine: Engine | None = None, tag: str = "manual",
                     keep: int = DEFAULT_KEEP) -> Path:
    """Create an explicit recovery point, then prune older manual snapshots."""
    if keep < 1:
        raise ValueError("A recovery point requires keep >= 1.")
    eng = _resolve(engine)
    dest = create_backup(engine=eng, tag=tag)
    prune(keep=keep, engine=eng, preserve=dest)
    return dest


def restore_backup(source: Path, *, engine: Engine | None = None) -> Path:
    """Replace the live DB with ``source`` (a backup file), returning the DB path.

    Safety: snapshots the CURRENT live DB first (tag ``pre-restore``) so a mistaken
    restore is itself reversible — the very failure mode that motivated backups. Verifies
    ``source`` passes an integrity check before overwriting, so a corrupt backup can't
    clobber a good DB. The caller stops the backend and obtains user confirmation."""
    eng = _resolve(engine)
    source = source.resolve()
    if not source.exists():
        raise FileNotFoundError(f"Backup not found: {source}")
    db_path = _sqlite_path(eng)
    if source == db_path:
        raise ValueError("Choose a backup file, not the live database.")
    candidate: Path | None = None
    try:
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as saved:
            _check_integrity(saved, source)
            deletion_ledger = _read_deletion_ledger(db_path)
            sequences = {}
            if db_path.exists():
                with closing(sqlite3.connect(str(db_path))) as live:
                    sequences = _read_sequences(live)
            # Prepare and validate the complete restore before replacing live data.
            with NamedTemporaryFile(dir=db_path.parent, prefix="restore-", suffix=".db", delete=False) as temporary:
                candidate = Path(temporary.name)
            with closing(sqlite3.connect(str(candidate))) as prepared:
                saved.backup(prepared)
        _upgrade_restored_schema(candidate)
        _reapply_deletion_ledger(candidate, deletion_ledger)
        _reset_restored_authority(candidate)
        _preserve_sequences(candidate, sequences)
        with closing(sqlite3.connect(str(candidate))) as prepared:
            _check_integrity(prepared, candidate)
            if db_path.exists():
                create_backup(engine=eng, tag="pre-restore")
            eng.dispose()
            # SQLite's journal protocol prevents crash-left WAL pages from overlaying the copy.
            with closing(sqlite3.connect(str(db_path))) as destination:
                prepared.backup(destination)
        with closing(sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True)) as restored:
            _check_integrity(restored, db_path)
    finally:
        if candidate is not None:
            candidate.unlink(missing_ok=True)
    return db_path


def _check_integrity(conn: sqlite3.Connection, path: Path) -> None:
    result = conn.execute("PRAGMA integrity_check").fetchone()
    if not result or result[0] != "ok":
        raise RuntimeError(f"Database failed integrity check ({result}): {path}")
    if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise RuntimeError(f"Database has invalid foreign keys: {path}")


def _read_sequences(conn: sqlite3.Connection) -> dict[str, int]:
    if not _table_exists(conn, "sqlite_sequence"):
        return {}
    return {name: int(seq) for name, seq in conn.execute("SELECT name, seq FROM sqlite_sequence")}


def _preserve_sequences(db_path: Path, sequences: dict[str, int]) -> None:
    """Restoring data cannot rewind identities held by browsers or deferred work."""
    if not sequences:
        return
    with closing(sqlite3.connect(str(db_path))) as conn, conn:
        if not _table_exists(conn, "sqlite_sequence"):
            raise RuntimeError("This snapshot cannot preserve record identities; use a migrated backup.")
        current = _read_sequences(conn)
        for name, seq in sequences.items():
            if not _table_exists(conn, name):
                continue
            value = max(seq, current.get(name, 0))
            updated = conn.execute("UPDATE sqlite_sequence SET seq = ? WHERE name = ?", (value, name))
            if not updated.rowcount:
                conn.execute("INSERT INTO sqlite_sequence (name, seq) VALUES (?, ?)", (name, value))


def _upgrade_restored_schema(db_path: Path) -> None:
    """Migrate a project snapshot in isolation before publishing it as the live database."""
    with closing(sqlite3.connect(str(db_path))) as conn:
        if not _table_exists(conn, "alembic_version"):
            raise RuntimeError("Application snapshots require an Alembic revision; unversioned schemas cannot be restored safely.")
    backend = Path(__file__).resolve().parents[2]
    config = Config(str(backend / "alembic.ini"))
    config.set_main_option("script_location", str(backend / "alembic"))
    prepared_engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        with prepared_engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
    finally:
        prepared_engine.dispose()


def _read_deletion_ledger(db_path: Path) -> list[tuple[str, int, str, str, str]]:
    """Capture the current non-identifying ledger before replacing the main DB file."""
    if not db_path.exists():
        return []
    with closing(sqlite3.connect(str(db_path))) as conn:
        if not _table_exists(conn, "retention_deletions"):
            return []
        return list(
            conn.execute(
                "SELECT record_kind, record_id, retention_rule, due_on, deleted_at "
                "FROM retention_deletions"
            )
        )


def _reapply_deletion_ledger(
    db_path: Path, ledger: list[tuple[str, int, str, str, str]]
) -> None:
    """Prevent an older backup from resurrecting aggregates already purged later."""
    if not ledger:
        return
    with closing(sqlite3.connect(str(db_path))) as conn, conn:
        conn.execute("PRAGMA foreign_keys=ON")
        restored_ledger = list(
            conn.execute(
                "SELECT record_kind, record_id, retention_rule, due_on, deleted_at "
                "FROM retention_deletions"
            )
        )
        entries = {}
        for row in [*restored_ledger, *ledger]:
            key = (row[0], row[1])
            if key not in entries or _utc_timestamp(row[4]) > _utc_timestamp(entries[key][4]):
                entries[key] = row
        covered_records = []
        for row in entries.values():
            kind, record_id, retention_rule, due_on, deleted_at = row
            covered = _record_is_covered(conn, kind, record_id, deleted_at)
            if covered:
                covered_records.append((kind, record_id))
            conn.execute(
                "INSERT INTO retention_deletions "
                "(record_kind, record_id, retention_rule, due_on, deleted_at) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT(record_kind, record_id) DO UPDATE SET "
                "retention_rule = excluded.retention_rule, due_on = excluded.due_on, deleted_at = excluded.deleted_at",
                (kind, record_id, retention_rule, due_on, deleted_at),
            )

    prepared_engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        with prepared_engine.begin() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            with Session(bind=connection) as db:
                for kind, record_id in covered_records:
                    if kind == "application":
                        application = db.get(Application, record_id)
                        if application is not None:
                            erase_application(db, application)
                    elif kind == "applicant_draft":
                        draft = db.get(ApplicantDraft, record_id)
                        if draft is not None:
                            erase_draft(db, draft)
                prune_unowned_results(db)
                db.flush()
    finally:
        prepared_engine.dispose()


def _reset_restored_authority(db_path: Path) -> None:
    """A stopped process cannot resume credentials or claimed work from a snapshot."""
    prepared_engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    now = datetime.now(UTC)
    try:
        with prepared_engine.begin() as connection:
            connection.execute(update(BrowserSession).where(BrowserSession.revoked_at.is_(None)).values(revoked_at=now))
            connection.execute(update(MagicLinkToken).where(MagicLinkToken.revoked_at.is_(None)).values(revoked_at=now))
            queued = EmailDelivery.state == EmailDeliveryState.QUEUED
            # These intents issue credentials when rebuilt; ordinary notifications
            # remain durable and recheck their lifecycle in the existing outbox.
            credential_intent = EmailDelivery.retry_intent["type"].as_string().in_(
                ["magic_link", "application_confirmation", "application_opening"])
            connection.execute(update(EmailDelivery).where(queued, credential_intent).values(
                state=EmailDeliveryState.FAILED, retry_intent=None,
                quota_blocked=False, last_error_code="RecoveryReset"))
            connection.execute(update(EmailDelivery).where(queued).values(last_error_code="RecoveryReset"))
            connection.execute(update(RunLock).values(
                holder_user_id=None, kind=None, held_since=None, renewed_at=None))
            connection.execute(update(DailyMaintenanceRun).where(DailyMaintenanceRun.status == "running").values(
                status="failed", lease_expires_at=now, last_error_code="RecoveryReset"))
    finally:
        prepared_engine.dispose()


def _utc_timestamp(value: str) -> datetime:
    return as_utc(datetime.fromisoformat(value))


def _record_is_covered(conn: sqlite3.Connection, kind: str, record_id: int, deleted_at: str) -> bool:
    table = {"application": "applications", "applicant_draft": "applicant_drafts"}.get(kind)
    if table is None:
        raise RuntimeError(f"Unknown deletion record kind: {kind}")
    row = conn.execute(f"SELECT created_at FROM {table} WHERE id = ?", (record_id,)).fetchone()
    if row is None:
        return True
    created, deleted = _utc_timestamp(row[0]), _utc_timestamp(deleted_at)
    if created > deleted:
        return False  # A later generation is not the record covered by this deletion.
    if record_id < RECORD_ID_FLOOR and created.microsecond == 0 and created == deleted.replace(microsecond=0):
        raise RuntimeError("This legacy snapshot has an ambiguous reused record ID; choose a different backup.")
    return True


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        ).fetchone()
        is not None
    )


def main(argv: list[str] | None = None, *, engine: Engine | None = None) -> None:
    """Manual recovery CLI; arguments are data and restores require confirmation."""
    parser = argparse.ArgumentParser(description="Back up or restore the local SQLite database.")
    parser.add_argument("action", choices=["backup", "list", "restore"], nargs="?", default="backup")
    parser.add_argument("target", nargs="?")
    parser.add_argument("--tag", default="manual")
    parser.add_argument("--latest", action="store_true")
    args = parser.parse_args(argv)
    if args.target and (args.action != "restore" or args.latest):
        parser.error("Use either a restore target or --latest, not both.")
    if args.latest and args.action != "restore":
        parser.error("--latest applies only to restore.")
    eng = _resolve(engine)
    if args.action == "backup":
        dest = create_and_prune(engine=eng, tag=args.tag)
        print(f"Backup written: {dest}  ({dest.stat().st_size / 1_000_000:.1f} MB)")
        print(f"{len(list_backups(eng))} backup(s) retained in {backups_dir(eng)}")
        return
    backups = list_backups(eng)
    if args.action == "list":
        for path in backups:
            print(path.name)
        return
    target = args.target
    if args.latest:
        if not backups:
            parser.error("No backups are available.")
        target = str(backups[0])
    elif target is None:
        print("Available backups (newest first):")
        for path in backups:
            print(path.name)
        target = input("Enter a backup filename to restore (or blank to cancel): ").strip()
    if not target:
        print("Restore cancelled.")
        return
    source = Path(target)
    if not source.is_file():
        source = backups_dir(eng) / target
    if not source.is_file():
        parser.error(f"No such backup: {target}")
    print(f"Stop the backend before restoring. This will replace the live DB with:\n  {source}")
    print("The current DB is snapshotted first (tag pre-restore).")
    if input("Type RESTORE to continue: ") != "RESTORE":
        print("Restore cancelled.")
        return
    restored = restore_backup(source, engine=eng)
    print(f"Restored {restored} from {source}")


if __name__ == "__main__":
    main()
