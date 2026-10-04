"""Own an AI stream's lease renewal, fenced commits, and cleanup."""

import logging
from collections.abc import Generator
from threading import Event, Thread

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.ai.pricing import observe_cost_meters
from app.core.work_cancellation import (
    WorkCancelled,
    cancellation_scope,
    check_cancelled,
)
from app.schemas.events import ErrorEvent, emit
from app.services.cost_report import RUN_COST_RECORDER_KEY, RunCostRecorder
from app.services.run_lock import (
    RunLease,
    RunLeaseLost,
    release_run_lock,
    renew_run_lock,
)
from app.services.work_stream import WorkStreamingResponse

RENEWAL_INTERVAL_SECONDS = 60
log = logging.getLogger(__name__)


def leased_run_stream(
    db: Session, lease: RunLease, events: Generator[str], *, phase: str, cancelled: Event | None = None,
    cost: RunCostRecorder | None = None,
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
            with cancellation_scope(stop), observe_cost_meters(cost.observe if cost is not None else None):
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
            try:
                release_run_lock(db, lease)
            finally:
                if db.info.get(RUN_COST_RECORDER_KEY) is cost:
                    db.info.pop(RUN_COST_RECORDER_KEY, None)
                if cost is not None:
                    cost.record_interrupted(bind)


class RunStreamingResponse(WorkStreamingResponse):
    """Add lease ownership to the shared HTTP worker-stream lifetime."""

    def __init__(self, db: Session, lease: RunLease, events: Generator[str], *, phase: str,
                 cost: RunCostRecorder | None = None):
        self._db, self._lease, self._run_events = db, lease, events
        self._started = False
        self._cost = cost
        if cost is not None:
            db.info[RUN_COST_RECORDER_KEY] = cost
        cancelled = Event()

        def leased_content() -> Generator[str]:
            self._started = True
            yield from leased_run_stream(db, lease, events, phase=phase, cancelled=cancelled, cost=cost)

        super().__init__(leased_content(), cancelled=cancelled)

    def _close(self) -> None:
        super()._close()
        if not self._started:
            self._run_events.close()
            self._db.rollback()
            release_run_lock(self._db, self._lease)
            if self._db.info.get(RUN_COST_RECORDER_KEY) is self._cost:
                self._db.info.pop(RUN_COST_RECORDER_KEY, None)
