"""Interrupted consumers cancel queued calls and release their database writer promptly."""

from threading import Event, Thread

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.ai.analysis import run_in_pool
from app.db.models import Application, Base, RunLock, User, UserRole
from app.services.run_lock import RunLeaseLost, acquire_run_lock, ensure_lock_row
from app.services.run_stream import leased_run_stream


def held_second_call():
    started, finish, completed = Event(), Event(), Event()
    calls = []

    def call(item):
        calls.append(item)
        if item == 2:
            started.set()
            try:
                assert finish.wait(3), "active call was not released by the test"
            finally:
                completed.set()
        return item

    return call, calls, started, finish, completed


def test_closing_a_pool_cancels_queued_calls_without_waiting_for_active_calls() -> None:
    call, calls, started, finish, completed = held_second_call()
    results = run_in_pool([1, 2, 3, 4], call=call, max_workers=1)
    try:
        assert next(results) == (1, 1, None)
        assert started.wait(2)
        results.close()
        assert not completed.is_set()
        assert calls == [1, 2]
    finally:
        finish.set()
        results.close()
    assert completed.wait(2)
    assert calls == [1, 2]


def test_failed_result_releases_writer_before_active_calls_finish(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'pool-cancellation.db').as_posix()}",
        connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    call, calls, started, finish, completed = held_second_call()
    written, attempted = Event(), Event()
    contender_errors = []

    def competing_write():
        try:
            assert written.wait(3)
            with engine.begin() as connection:
                connection.exec_driver_sql("PRAGMA busy_timeout=500")
                connection.exec_driver_sql("UPDATE users SET display_name='Contender' WHERE id=1")
        except Exception as error:
            contender_errors.append(error)
        finally:
            attempted.set()

    contender = Thread(target=competing_write)
    try:
        with Session(engine) as db:
            ensure_lock_row(db)
            db.add(User(id=1, email="synthetic@example.com", display_name="Synthetic", role=UserRole.MEMBER))
            db.commit()
            lease = acquire_run_lock(db, user_id=1, kind="rank")
            contender.start()

            def source():
                for _item, _result, _error in run_in_pool([1, 2, 3, 4], call=call, max_workers=1):
                    assert started.wait(2)
                    db.add(Application(primary_email="pending@example.com", raw_row={}, raw_row_hash="pending"))
                    db.flush()
                    written.set()
                    raise RunLeaseLost
                    yield "unreachable\n"

            lines = list(leased_run_stream(db, lease, source(), phase="scores"))
            assert len(lines) == 1
            assert not completed.is_set()
            assert attempted.wait(2)
            assert contender_errors == []
            assert db.scalar(select(Application)) is None
            assert db.get(RunLock, 1, populate_existing=True).holder_user_id is None
            assert calls == [1, 2]
    finally:
        finish.set()
        written.set()
        if contender.ident is not None:
            contender.join(3)
        completed.wait(3)
        engine.dispose()
