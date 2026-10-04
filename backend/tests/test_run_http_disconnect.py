"""The real ASGI response owns cleanup on disconnect, send failure, and blocked work."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import anyio
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from starlette.requests import ClientDisconnect

from app.ai.analysis import run_in_pool
from app.core.work_cancellation import cancellation_event
from app.db.models import Application, Base, RunLock, User, UserRole
from app.services import run_stream
from app.services.run_lock import acquire_run_lock, ensure_lock_row
from app.services.run_stream import RunStreamingResponse, leased_run_stream
from app.services.stream_worker import StreamWorker
from tests.db_support import memory_engine


def test_cancellation_context_is_bound_separately_when_resumes_change_threads() -> None:
    with Session(memory_engine()) as db:
        lease = setup(db)
        cancelled = Event()
        observed = []

        def source():
            for line in ("first", "second"):
                observed.append(cancellation_event())
                yield line

        stream = leased_run_stream(db, lease, source(), phase="criteria", cancelled=cancelled)

        def resume():
            return next(stream), cancellation_event()

        try:
            with ThreadPoolExecutor(max_workers=1) as first, ThreadPoolExecutor(max_workers=1) as second:
                assert first.submit(resume).result() == ("first", None)
                assert second.submit(resume).result() == ("second", None)
            assert observed == [cancelled, cancelled]
        finally:
            stream.close()
        assert cancellation_event() is None


def setup(db):
    ensure_lock_row(db)
    db.add(User(id=1, email="synthetic@example.com", display_name="Synthetic", role=UserRole.MEMBER))
    db.commit()
    return acquire_run_lock(db, user_id=1, kind="rank")


def engine_for(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'http-run.db').as_posix()}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return engine


@pytest.mark.anyio
@pytest.mark.parametrize("version", ["2.3", "2.4"])
@pytest.mark.parametrize("stage", ["start", "body"])
async def test_disconnect_releases_lease_and_rolls_back_without_garbage_collection(tmp_path, version, stage) -> None:
    engine = engine_for(tmp_path)
    disconnected = anyio.Event()
    closed = []
    try:
        with Session(engine) as db:
            lease = setup(db)

            def source():
                try:
                    db.add(Application(primary_email="pending@example.com", raw_row={}, raw_row_hash="pending"))
                    db.flush()
                    yield "started\n"
                finally:
                    closed.append(True)

            response = RunStreamingResponse(db, lease, source(), phase="criteria")

            async def receive():
                await disconnected.wait()
                return {"type": "http.disconnect"}

            async def send(message):
                if message["type"] == f"http.response.{stage}":
                    if version == "2.4":
                        raise OSError("Synthetic send failure")
                    disconnected.set()
                    await anyio.sleep_forever()

            scope = {"type": "http", "asgi": {"spec_version": version}}
            if version == "2.4":
                with pytest.raises(ClientDisconnect):
                    await response(scope, receive, send)
            else:
                await response(scope, receive, send)
            # Keep the response referenced: cleanup must be explicit, not a GC side effect.
            assert response is not None
            assert closed == ([True] if stage == "body" else [])
            assert db.scalar(select(Application)) is None
            assert db.get(RunLock, 1, populate_existing=True).holder_user_id is None
            db.add(Application(primary_email="after@example.com", raw_row={}, raw_row_hash="after"))
            db.commit()  # the stream's commit guard is gone
    finally:
        engine.dispose()


@pytest.mark.anyio
@pytest.mark.parametrize("worker_kind", ["pool", "callback"])
async def test_disconnect_stops_a_silent_wait_and_heartbeat_before_provider_returns(tmp_path, monkeypatch, worker_kind) -> None:
    engine = engine_for(tmp_path)
    started, finish, finished = Event(), Event(), Event()
    closed, calls, renewals = [], [], []
    renew = run_stream.renew_run_lock
    monkeypatch.setattr(run_stream, "RENEWAL_INTERVAL_SECONDS", 0.01)

    def observe(db, lease, **kwargs):
        accepted = renew(db, lease, **kwargs)
        renewals.append(accepted)
        return accepted

    monkeypatch.setattr(run_stream, "renew_run_lock", observe)

    def blocked(item):
        calls.append(item)
        started.set()
        try:
            assert finish.wait(3)
            return item
        finally:
            finished.set()

    try:
        with Session(engine) as db:
            lease = setup(db)

            def source():
                try:
                    yield "started\n"
                    if worker_kind == "pool":
                        for _item, _result, _error in run_in_pool([1, 2, 3, 4], call=blocked, max_workers=1):
                            db.add(Application(primary_email="must-not-save@example.com", raw_row={}, raw_row_hash="cancelled"))
                            db.commit()
                            yield "must not reach\n"
                    else:
                        worker = StreamWorker()
                        worker.start(lambda _put: blocked(1))
                        for _ping, item in worker.drain("criteria"):
                            yield str(item)
                finally:
                    closed.append(True)

            response = RunStreamingResponse(db, lease, source(), phase="criteria")

            async def receive():
                assert await anyio.to_thread.run_sync(started.wait, 2)
                await anyio.sleep(0.04)
                return {"type": "http.disconnect"}

            async def send(_message):
                pass

            with anyio.fail_after(2):
                await response({"type": "http", "asgi": {"spec_version": "2.3"}}, receive, send)
            assert not finished.is_set()
            assert closed == [True]
            assert calls == [1]
            assert db.scalar(select(Application)) is None
            assert db.get(RunLock, 1, populate_existing=True).holder_user_id is None
            renewal_count = len(renewals)
            await anyio.sleep(0.04)
            assert len(renewals) == renewal_count
    finally:
        finish.set()
        if started.is_set():
            assert await anyio.to_thread.run_sync(finished.wait, 2)
        engine.dispose()
