"""Own an AI stream's lease renewal, fenced commits, and cleanup."""

import logging
from collections.abc import Generator, Iterator
from contextlib import closing
from threading import Event, Thread

from sqlalchemy import event
from sqlalchemy.orm import Session

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
    db: Session, lease: RunLease, events: Generator[str], *, phase: str,
) -> Iterator[str]:
    """Keep a live run leased during provider waits and guard all commits in its session.

    The renewal thread has its own session and never sees request ORM objects. The
    before_commit guard fences pending writes in their own transaction, including
    commits made by pass helpers. Closing the response rolls back pending work,
    closes its source generator, stops renewal, and releases only this acquisition.
    """
    stop = Event()
    lost = Event()
    bind = db.get_bind()

    def renew_while_waiting() -> None:
        while not stop.wait(RENEWAL_INTERVAL_SECONDS):
            try:
                with Session(bind=bind) as renewal_db:
                    if not renew_run_lock(renewal_db, lease):
                        lost.set()
                        return
            except Exception as error:
                # A short database outage does not immediately abandon a live lease.
                # Subsequent heartbeats retry; the commit guard still requires a live owner.
                log.warning("Run lease renewal failed: %s", type(error).__name__)

    def guard_commit(session: Session) -> None:
        if lost.is_set() or not renew_run_lock(session, lease, commit=False):
            lost.set()
            raise RunLeaseLost

    heartbeat = Thread(target=renew_while_waiting, name="ai-run-lease", daemon=True)
    event.listen(db, "before_commit", guard_commit)
    try:
        heartbeat.start()
        with closing(events):
            for line in events:
                if lost.is_set():
                    raise RunLeaseLost
                yield line
    except RunLeaseLost:
        db.rollback()
        yield emit(ErrorEvent(phase=phase,
            message="This run stopped early. Review saved results before running again."))
    finally:
        event.remove(db, "before_commit", guard_commit)
        # Release the writer before joining a heartbeat that may be waiting for it.
        db.rollback()
        stop.set()
        if heartbeat.ident is not None:
            heartbeat.join()
        release_run_lock(db, lease)
