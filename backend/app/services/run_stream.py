"""Own an AI stream's lease renewal, fenced commits, and cleanup."""

import logging
from collections.abc import Generator
from threading import Event, Thread

import anyio
from sqlalchemy import event
from sqlalchemy.orm import Session
from starlette.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

from app.core.work_cancellation import (
    WorkCancelled,
    cancellation_scope,
    check_cancelled,
)
from app.schemas.events import ErrorEvent, emit
from app.services.run_lock import (
    RunLease,
    RunLeaseLost,
    release_run_lock,
    renew_run_lock,
)

RENEWAL_INTERVAL_SECONDS = 60
log = logging.getLogger(__name__)


def leased_run_stream(
    db: Session, lease: RunLease, events: Generator[str], *, phase: str, cancelled: Event | None = None,
) -> Generator[str]:
    """Keep a live run leased during provider waits and guard all commits in its session.

    The renewal thread has its own session and never sees request ORM objects. The
    before_commit guard fences pending writes in their own transaction, including
    commits made by pass helpers. Closing the response rolls back pending work,
    closes its source generator, stops renewal, and releases only this acquisition.
    """
    stop = cancelled if cancelled is not None else Event()
    lost = Event()
    bind = db.get_bind()

    def renew_while_waiting() -> None:
        while not stop.wait(RENEWAL_INTERVAL_SECONDS):
            try:
                with Session(bind=bind) as renewal_db:
                    if not renew_run_lock(renewal_db, lease):
                        lost.set()
                        stop.set()
                        return
            except Exception as error:
                # A short database outage does not immediately abandon a live lease.
                # Subsequent heartbeats retry; the commit guard still requires a live owner.
                log.warning("Run lease renewal failed: %s", type(error).__name__)

    def guard_commit(session: Session) -> None:
        if stop.is_set() and not lost.is_set():
            raise WorkCancelled
        if lost.is_set() or not renew_run_lock(session, lease, commit=False):
            lost.set()
            stop.set()
            raise RunLeaseLost

    heartbeat = Thread(target=renew_while_waiting, name="ai-run-lease", daemon=True)
    event.listen(db, "before_commit", guard_commit)
    try:
        heartbeat.start()
        while True:
            # ASGI may resume a synchronous generator on a different worker thread.
            # Bind and reset context around each resume, never across a yield.
            with cancellation_scope(stop):
                check_cancelled()
                try:
                    line = next(events)
                except StopIteration:
                    break
                check_cancelled()
            yield line
    except (RunLeaseLost, WorkCancelled) as error:
        db.rollback()
        if isinstance(error, RunLeaseLost) or lost.is_set():
            yield emit(ErrorEvent(phase=phase,
                message="This run stopped early. Review saved results before running again."))
    finally:
        stop.set()
        try:
            with cancellation_scope(stop):
                events.close()
        finally:
            event.remove(db, "before_commit", guard_commit)
            # Release the writer before joining a heartbeat that may be waiting for it.
            db.rollback()
            if heartbeat.ident is not None:
                heartbeat.join()
            release_run_lock(db, lease)


class RunStreamingResponse(StreamingResponse):
    """Own source cleanup even when ASGI stops before consuming the first body chunk."""

    def __init__(self, db: Session, lease: RunLease, events: Generator[str], *, phase: str):
        self._db, self._lease, self._events = db, lease, events
        self._cancelled = Event()
        self._started = False

        def content() -> Generator[str]:
            self._started = True
            yield from leased_run_stream(db, lease, events, phase=phase, cancelled=self._cancelled)

        self._content = content()
        super().__init__(self._content, media_type="application/x-ndjson")

    def _close(self) -> None:
        self._content.close()
        if not self._started:
            # Closing an unstarted generator does not enter its finally block.
            self._events.close()
            self._db.rollback()
            release_run_lock(self._db, self._lease)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        async def monitored_receive():
            message = await receive()
            if message["type"] == "http.disconnect":
                self._cancelled.set()
            return message

        async def monitored_send(message):
            try:
                await send(message)
            except BaseException:
                self._cancelled.set()
                raise

        try:
            await super().__call__(scope, monitored_receive, monitored_send)
        finally:
            self._cancelled.set()
            # Disconnect cancellation must not cancel its own database cleanup.
            with anyio.CancelScope(shield=True):
                await anyio.to_thread.run_sync(self._close)
                await self.body_iterator.aclose()
