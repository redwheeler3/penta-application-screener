"""Backup/restore of the local SQLite DB (motivated by a real data-loss incident).

Uses a real on-disk temp DB with its own engine — VACUUM INTO and integrity checks need
a genuine SQLite file, not an in-memory one — passed explicitly to the backup functions,
so nothing touches the project's real database. This also exercises the ``engine=``
parameter that lets the request path back up a test's overridden DB rather than the app's.
"""

from datetime import datetime

import pytest
from sqlalchemy import create_engine, text

from app.services import backup


@pytest.fixture
def temp_engine(tmp_path):
    """A populated on-disk SQLite engine under a temp dir."""
    db_path = tmp_path / "data" / "penta_screener.db"
    db_path.parent.mkdir(parents=True)
    eng = create_engine(f"sqlite:///{db_path}")
    with eng.begin() as conn:
        conn.execute(text("CREATE TABLE runs (id INTEGER PRIMARY KEY, note TEXT)"))
        conn.execute(text("INSERT INTO runs (note) VALUES ('run-1'), ('run-2')"))
    return eng


def test_create_backup_is_a_valid_consistent_copy(temp_engine):
    dest = backup.create_backup(engine=temp_engine, tag="rank")

    assert dest.exists()
    assert dest.parent.name == "backups"
    assert "rank" in dest.name
    # The snapshot is a real, queryable DB with the source's rows.
    snap = create_engine(f"sqlite:///{dest}")
    with snap.connect() as conn:
        assert conn.execute(text("PRAGMA integrity_check")).scalar() == "ok"
        assert conn.execute(text("SELECT count(*) FROM runs")).scalar() == 2


def test_prune_keeps_only_the_newest(temp_engine):
    for i in range(5):
        backup.create_backup(engine=temp_engine, tag="t",
                             timestamp=datetime(2026, 7, 16, 10, 0, i))

    removed = backup.prune(keep=2, engine=temp_engine)

    assert len(removed) == 3
    assert len(backup.list_backups(temp_engine)) == 2


def test_restore_replaces_db_and_snapshots_current_first(temp_engine):
    good = backup.create_backup(engine=temp_engine, tag="good")  # snapshot with 2 rows

    # Mutate the live DB so restore has something to roll back.
    with temp_engine.begin() as conn:
        conn.execute(text("DELETE FROM runs"))

    before = len(backup.list_backups(temp_engine))
    backup.restore_backup(good, engine=temp_engine)
    after = len(backup.list_backups(temp_engine))

    # A pre-restore snapshot of the (emptied) DB was taken — the restore is reversible.
    assert after == before + 1
    assert any("pre-restore" in p.name for p in backup.list_backups(temp_engine))
    # The live DB file now has the restored rows again (fresh engine: the file was replaced).
    db_path = backup._sqlite_path(temp_engine)
    live = create_engine(f"sqlite:///{db_path}")
    with live.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM runs")).scalar() == 2


def test_restore_rejects_a_corrupt_backup(temp_engine, tmp_path):
    bogus = tmp_path / "corrupt.db"
    bogus.write_bytes(b"this is not a sqlite database")

    # A corrupt backup must be rejected before it can clobber the live DB.
    with pytest.raises(Exception, match=r"integrity|malformed|not a database"):
        backup.restore_backup(bogus, engine=temp_engine)


def test_restore_does_not_resurrect_a_retention_deletion(temp_engine):
    with temp_engine.begin() as conn:
        conn.execute(text("CREATE TABLE applications (id INTEGER PRIMARY KEY)"))
        conn.execute(
            text(
                "CREATE TABLE application_notes (id INTEGER PRIMARY KEY, "
                "application_id INTEGER NOT NULL)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE retention_deletions (id INTEGER PRIMARY KEY, "
                "record_kind VARCHAR(30) NOT NULL, record_id INTEGER NOT NULL, "
                "retention_rule VARCHAR(50) NOT NULL, due_on DATE NOT NULL, "
                "deleted_at DATETIME NOT NULL, UNIQUE(record_kind, record_id))"
            )
        )
        conn.execute(text("INSERT INTO applications (id) VALUES (42)"))
        conn.execute(
            text("INSERT INTO application_notes (application_id) VALUES (42)")
        )
    before_deletion = backup.create_backup(engine=temp_engine, tag="before-deletion")

    with temp_engine.begin() as conn:
        conn.execute(text("DELETE FROM application_notes WHERE application_id = 42"))
        conn.execute(text("DELETE FROM applications WHERE id = 42"))
        conn.execute(
            text(
                "INSERT INTO retention_deletions "
                "(record_kind, record_id, retention_rule, due_on, deleted_at) "
                "VALUES ('application', 42, 'one_year', '2026-08-26', "
                "'2026-08-26 12:00:00')"
            )
        )

    backup.restore_backup(before_deletion, engine=temp_engine)

    db_path = backup._sqlite_path(temp_engine)
    restored = create_engine(f"sqlite:///{db_path}")
    with restored.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM applications")).scalar() == 0
        assert conn.execute(text("SELECT count(*) FROM application_notes")).scalar() == 0
        assert conn.execute(text("SELECT count(*) FROM retention_deletions")).scalar() == 1


def test_in_memory_session_snapshot_is_a_noop_not_a_cwd_dump(tmp_path, monkeypatch):
    # In-memory engines have no file to snapshot and must not create a backup directory.
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    # A temporary cwd makes any accidental backup write observable to this test.
    monkeypatch.chdir(tmp_path)
    mem = create_engine("sqlite:///:memory:")
    with Session(mem) as session:
        result = backup.create_from_session(session, tag="rank")

    assert result is None
    assert not (tmp_path / "backups").exists()


def test_sqlite_path_rejects_in_memory(tmp_path):
    from sqlalchemy import create_engine

    with pytest.raises(RuntimeError, match="file-backed"):
        backup._sqlite_path(create_engine("sqlite:///:memory:"))
