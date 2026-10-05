"""Backup/restore of the local SQLite DB (motivated by a real data-loss incident).

Uses a real on-disk temp DB with its own engine — VACUUM INTO and integrity checks need
a genuine SQLite file, not an in-memory one — passed explicitly to the backup functions,
so nothing touches the project's real database.
"""

import sqlite3
import subprocess
import sys
from contextlib import closing
from datetime import datetime

import pytest
from sqlalchemy import create_engine, event, text

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
    dest = backup.create_backup(engine=temp_engine, tag="manual")

    assert dest.exists()
    assert dest.parent.name == "backups"
    assert "manual" in dest.name
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


def test_cli_treats_quoted_labels_as_data(temp_engine, capsys):
    backup.main(["backup", "--tag=synthetic's quoted label"], engine=temp_engine)
    [saved] = backup.list_backups(temp_engine)
    assert "synthetic-s-quoted-label" in saved.name
    assert "Backup written:" in capsys.readouterr().out


def test_cli_resolves_bare_backup_names_and_cancel_keeps_live_data(temp_engine, monkeypatch, capsys):
    saved = backup.create_backup(engine=temp_engine)
    monkeypatch.setattr("builtins.input", lambda _prompt: "CANCEL")
    backup.main(["restore", saved.name], engine=temp_engine)
    assert "Restore cancelled." in capsys.readouterr().out
    assert len(backup.list_backups(temp_engine)) == 1
    with temp_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM runs")).scalar() == 2


def test_cli_restores_a_quoted_path_only_after_confirmation(temp_engine, monkeypatch, capsys):
    import shutil

    saved = backup.create_backup(engine=temp_engine)
    quoted = saved.parent / "synthetic's backup.db"
    shutil.copy2(saved, quoted)
    with temp_engine.begin() as conn:
        conn.execute(text("INSERT INTO runs (note) VALUES ('later synthetic row')"))
    monkeypatch.setattr("builtins.input", lambda _prompt: "RESTORE")
    backup.main(["restore", str(quoted)], engine=temp_engine)
    assert "Restored " in capsys.readouterr().out
    with temp_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM runs")).scalar() == 2


def test_restore_preserves_the_live_identity_high_water_mark(temp_engine):
    with temp_engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE identities (id INTEGER PRIMARY KEY AUTOINCREMENT, marker TEXT)")
        conn.exec_driver_sql("INSERT INTO identities (marker) VALUES ('original')")
    saved = backup.create_backup(engine=temp_engine)
    with temp_engine.begin() as conn:
        conn.exec_driver_sql("INSERT INTO identities (marker) VALUES ('later')")
        later_id = conn.exec_driver_sql("SELECT MAX(id) FROM identities").scalar_one()
    backup.restore_backup(saved, engine=temp_engine)
    with temp_engine.begin() as conn:
        conn.exec_driver_sql("INSERT INTO identities (marker) VALUES ('replacement')")
        assert conn.exec_driver_sql("SELECT MAX(id) FROM identities").scalar_one() > later_id


def test_restore_does_not_delete_a_later_generation_of_a_legacy_id(temp_engine):
    with temp_engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE applications (id INTEGER PRIMARY KEY, created_at TEXT, marker TEXT)")
        conn.exec_driver_sql("INSERT INTO applications VALUES (1, '2026-10-04 12:00:00', 'new generation')")
    saved = backup.create_backup(engine=temp_engine)
    path = backup._sqlite_path(temp_engine)
    with sqlite3.connect(path) as conn:
        backup._ensure_deletion_ledger(conn)
        conn.execute("INSERT INTO retention_deletions (record_kind, record_id, retention_rule, due_on, deleted_at) "
            "VALUES ('application', 1, 'one_year', '2026-10-01', '2026-10-01 12:00:00')")
    backup.restore_backup(saved, engine=temp_engine)
    with temp_engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT marker FROM applications WHERE id=1").scalar_one() == "new generation"


def test_ambiguous_legacy_restore_fails_before_replacing_live_data(temp_engine):
    with temp_engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE applications (id INTEGER PRIMARY KEY, created_at TEXT)")
        conn.exec_driver_sql("INSERT INTO applications VALUES (1, '2026-10-04 12:00:00')")
    saved = backup.create_backup(engine=temp_engine)
    path = backup._sqlite_path(temp_engine)
    with sqlite3.connect(path) as conn:
        backup._ensure_deletion_ledger(conn)
        conn.execute("INSERT INTO retention_deletions (record_kind, record_id, retention_rule, due_on, deleted_at) "
            "VALUES ('application', 1, 'one_year', '2026-10-04', '2026-10-04 12:00:00.500000')")
        conn.execute("INSERT INTO runs (note) VALUES ('live data')")
    with pytest.raises(RuntimeError, match="ambiguous"):
        backup.restore_backup(saved, engine=temp_engine)
    with temp_engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT count(*) FROM runs").scalar_one() == 3


def test_restore_rejects_a_corrupt_backup(temp_engine, tmp_path):
    bogus = tmp_path / "corrupt.db"
    bogus.write_bytes(b"this is not a sqlite database")

    # A corrupt backup must be rejected before it can clobber the live DB.
    with pytest.raises(Exception, match=r"integrity|malformed|not a database"):
        backup.restore_backup(bogus, engine=temp_engine)


def test_restore_replaces_crash_left_wal_and_preserves_a_recovery_snapshot(tmp_path):
    live = tmp_path / "synthetic-live.db"
    saved = tmp_path / "synthetic-backup.db"
    script = """
import os, sqlite3, sys
live = sqlite3.connect(sys.argv[1])
live.execute('PRAGMA journal_mode=WAL')
live.execute('PRAGMA wal_autocheckpoint=0')
live.execute('CREATE TABLE facts (value INTEGER)')
live.execute('INSERT INTO facts VALUES (1)')
live.commit()
saved = sqlite3.connect(sys.argv[2])
live.backup(saved)
saved.close()
live.execute('UPDATE facts SET value=2')
live.commit()
os._exit(0)
"""
    subprocess.run([sys.executable, "-c", script, str(live), str(saved)], check=True)
    assert live.with_name(live.name + "-wal").exists()
    engine = create_engine(f"sqlite:///{live.as_posix()}")

    @event.listens_for(engine, "connect")
    def use_wal(connection, _record):
        connection.execute("PRAGMA journal_mode=WAL")

    try:
        backup.restore_backup(saved, engine=engine)
        with closing(sqlite3.connect(live)) as restored:
            assert restored.execute("SELECT value FROM facts").fetchone()[0] == 1
        recovery = next(path for path in backup.list_backups(engine) if "pre-restore" in path.name)
        with closing(sqlite3.connect(recovery)) as current:
            assert current.execute("SELECT value FROM facts").fetchone()[0] == 2
        # The supplied engine also reopens the restored image after its pool was disposed.
        with engine.connect() as restored:
            assert restored.execute(text("SELECT value FROM facts")).scalar_one() == 1
    finally:
        engine.dispose()


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
                "CREATE TABLE application_committee_notes (id INTEGER PRIMARY KEY, "
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
        conn.execute(
            text("INSERT INTO application_committee_notes (application_id) VALUES (42)")
        )
    before_deletion = backup.create_backup(engine=temp_engine, tag="before-deletion")

    with temp_engine.begin() as conn:
        conn.execute(text("DELETE FROM application_notes WHERE application_id = 42"))
        conn.execute(
            text("DELETE FROM application_committee_notes WHERE application_id = 42")
        )
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
        assert (
            conn.execute(text("SELECT count(*) FROM application_committee_notes")).scalar()
            == 0
        )
        assert conn.execute(text("SELECT count(*) FROM retention_deletions")).scalar() == 1

def test_sqlite_path_rejects_in_memory(tmp_path):
    from sqlalchemy import create_engine

    with pytest.raises(RuntimeError, match="file-backed"):
        backup._sqlite_path(create_engine("sqlite:///:memory:"))


def test_restore_upgrades_producer_fk_before_replaying_deletions(tmp_path, monkeypatch):
    from pathlib import Path

    from alembic.config import Config

    from alembic import command
    from app.core.config import get_settings
    from app.db.models import RECORD_ID_FLOOR

    path = tmp_path / "retained-cache.db"
    url = f"sqlite:///{path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    get_settings.cache_clear()
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("script_location", str(Path(__file__).parents[1] / "alembic"))
    engine = create_engine(url)
    producer, consumer, result = RECORD_ID_FLOOR + 1, RECORD_ID_FLOOR + 2, RECORD_ID_FLOOR + 3
    try:
        command.upgrade(config, "a47e5c19b203")
        with engine.begin() as conn:
            for identity in (producer, consumer):
                conn.execute(text("INSERT INTO applications (id, primary_email, raw_row, raw_row_hash, normalized) VALUES (:id, :email, '{}', 'same', '{}')"),
                             {"id": identity, "email": f"synthetic{identity}@example.test"})
            conn.execute(text("INSERT INTO application_ai_results (id, application_id, kind, cache_key, model_id, prompt_version, output, input_tokens, output_tokens, cost_usd) VALUES (:id, :producer, 'screening', 'same', 'synthetic', 'v', '{\"flags\": []}', 100, 50, 0.123)"),
                         {"id": result, "producer": producer})
            conn.execute(text("INSERT INTO application_ai_selections (application_id, kind, result_id) VALUES (:consumer, 'screening', :result)"), {"consumer": consumer, "result": result})
        saved = backup.create_backup(engine=engine)
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO retention_deletions (record_kind, record_id, retention_rule, due_on, deleted_at) VALUES ('application', :producer, 'one_year', '2026-10-05', '2026-10-06 12:00:00')"), {"producer": producer})
        backup.restore_backup(saved, engine=engine)
        with engine.connect() as conn:
            assert conn.exec_driver_sql("SELECT producer_application_id, cost_usd FROM application_ai_results").one() == (producer, 0.123)
            assert conn.exec_driver_sql("SELECT application_id, result_id FROM application_ai_selections").one() == (consumer, result)
            assert conn.exec_driver_sql("SELECT id FROM applications").scalars().all() == [consumer]
            assert conn.exec_driver_sql("PRAGMA foreign_key_check").all() == []
    finally:
        engine.dispose()
        get_settings.cache_clear()
