"""Long waits keep their lease; a superseded run cannot commit or release its replacement."""

import json
from datetime import UTC, datetime, timedelta
from threading import Event

import pytest
from sqlalchemy import create_engine, event, insert, select
from sqlalchemy.orm import Session

from app.db.models import Application, Base, RunLock, User, UserRole
from app.services import run_lock, run_stream
from app.services.run_lock import (
    LEASE_TTL,
    acquire_run_lock,
    ensure_lock_row,
    rank_run_in_progress,
)
from app.services.run_stream import leased_run_stream
from tests.db_support import memory_engine

NOW = datetime(2026, 10, 3, 12, tzinfo=UTC)


def claim(db, monkeypatch):
    clock = [NOW]

    class Clock:
        @staticmethod
        def now(_timezone):
            return clock[0]

    monkeypatch.setattr(run_lock, "datetime", Clock)
    ensure_lock_row(db)
    db.add(User(id=1, email="synthetic@example.com", display_name="Synthetic", role=UserRole.MEMBER))
    db.commit()
    return acquire_run_lock(db, user_id=1, kind="rank"), clock


@pytest.mark.parametrize("write", ["orm", "core"])
def test_replaced_run_rolls_back_writes_and_keeps_same_members_new_lease(monkeypatch, write) -> None:
    with Session(memory_engine()) as db:
        lease, clock = claim(db, monkeypatch)
        replacement = []

        def source():
            yield "started\n"
            clock[0] = NOW + LEASE_TTL + timedelta(seconds=1)
            with Session(db.bind) as other:
                replacement.append(acquire_run_lock(other, user_id=1, kind="rank"))
            values = {"primary_email": "pending@example.com", "raw_row": {}, "raw_row_hash": "pending"}
            if write == "orm":
                db.add(Application(**values))
            else:
                db.execute(insert(Application), [values])
            db.commit()
            yield "must not finish\n"

        lines = list(leased_run_stream(db, lease, source(), phase="criteria"))
        assert replacement[0] is not None
        assert lines[0] == "started\n"
        assert json.loads(lines[1])["type"] == "error"
        assert len(lines) == 2
        assert db.scalar(select(Application)) is None
        lock = db.get(RunLock, 1, populate_existing=True)
        assert lock.holder_user_id == 1
        assert lock.held_since == replacement[0].acquired_at.replace(tzinfo=None)
        # The session's commit fence is removed during cleanup.
        db.add(Application(primary_email="after@example.com", raw_row={}, raw_row_hash="after"))
        db.commit()


def test_disconnect_closes_the_source_and_rolls_back_pending_work(monkeypatch) -> None:
    with Session(memory_engine()) as db:
        lease, _clock = claim(db, monkeypatch)
        closed = []

        def source():
            try:
                db.add(Application(primary_email="pending@example.com", raw_row={}, raw_row_hash="pending"))
                db.flush()
                yield "started\n"
            finally:
                closed.append(True)

        response = leased_run_stream(db, lease, source(), phase="criteria")
        assert next(response) == "started\n"
        response.close()
        assert closed == [True]
        assert db.scalar(select(Application)) is None
        assert db.get(RunLock, 1, populate_existing=True).holder_user_id is None


def test_commit_fences_before_autoflush_without_adding_a_commit(monkeypatch) -> None:
    with Session(memory_engine()) as db:
        lease, _clock = claim(db, monkeypatch)
        writes, commits = [], []

        def record(_connection, _cursor, statement, _params, _context, _many):
            if statement.startswith(("UPDATE", "INSERT")):
                writes.append(statement)

        event.listen(db.bind, "before_cursor_execute", record)
        event.listen(db, "after_commit", lambda _db: commits.append(True))

        def source():
            db.add(Application(primary_email="saved@example.com", raw_row={}, raw_row_hash="saved"))
            db.commit()
            assert len(commits) == 1
            yield "saved\n"

        assert list(leased_run_stream(db, lease, source(), phase="criteria")) == ["saved\n"]
        assert writes[0].startswith("UPDATE run_lock")
        assert writes[1].startswith("INSERT INTO applications")
        assert db.scalar(select(Application)) is not None


def test_heartbeat_renews_during_a_silent_wait_beyond_original_ttl(tmp_path, monkeypatch) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'run-lease.db').as_posix()}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    renewed = Event()
    renew = run_stream.renew_run_lock
    monkeypatch.setattr(run_stream, "RENEWAL_INTERVAL_SECONDS", 0.01)

    def observe(db, lease, **kwargs):
        success = renew(db, lease, **kwargs)
        if success and kwargs.get("commit", True) and run_lock.datetime.now(UTC) >= NOW + timedelta(minutes=14):
            renewed.set()
        return success

    monkeypatch.setattr(run_stream, "renew_run_lock", observe)
    with Session(engine) as db:
        lease, clock = claim(db, monkeypatch)

        def source():
            yield "waiting\n"

        response = leased_run_stream(db, lease, source(), phase="criteria")
        try:
            assert next(response) == "waiting\n"
            clock[0] = NOW + timedelta(minutes=14)
            assert renewed.wait(2)
            clock[0] = NOW + timedelta(minutes=17)
            with Session(engine) as contender:
                assert acquire_run_lock(contender, user_id=1, kind="rank") is None
                assert rank_run_in_progress(contender)
            assert db.get(RunLock, 1, populate_existing=True).held_since == NOW.replace(tzinfo=None)
        finally:
            response.close()
    engine.dispose()
