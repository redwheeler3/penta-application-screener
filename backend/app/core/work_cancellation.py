"""Cooperative cancellation for session-free work started by a streamed request."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from threading import Event

_current: ContextVar[Event | None] = ContextVar("work_cancellation", default=None)


class WorkCancelled(RuntimeError):
    """The owning request stopped; no follow-up work should start."""


def cancellation_event() -> Event | None:
    return _current.get()


def check_cancelled() -> None:
    stopped = cancellation_event()
    if stopped is not None and stopped.is_set():
        raise WorkCancelled


@contextmanager
def cancellation_scope(stopped: Event) -> Iterator[None]:
    """Bind cancellation for one synchronous resume; workers copy this context."""
    token = _current.set(stopped)
    try:
        yield
    finally:
        _current.reset(token)
