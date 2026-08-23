"""Bridge blocking callback-based work into an NDJSON response generator."""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable, Iterator
from typing import TypeVar, cast

from app.schemas.events import PingEvent, emit

ItemT = TypeVar("ItemT")
ResultT = TypeVar("ResultT")

HEARTBEAT_SECONDS = 15
_DONE = object()


class StreamWorker[ItemT, ResultT]:
    """Run blocking work in one thread while the request thread streams callback items.

    The heartbeat keeps otherwise-silent model calls alive through proxy idle timeouts. The
    caller remains responsible for translating items into job-specific NDJSON events.
    """

    def __init__(self) -> None:
        self._items: queue.Queue[ItemT | object] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._result: ResultT | None = None
        self._has_result = False
        self.error: Exception | None = None

    def start(self, work: Callable[[Callable[[ItemT], None]], ResultT]) -> None:
        if self._thread is not None:
            raise RuntimeError("StreamWorker can only be started once")

        def run() -> None:
            try:
                self._result = work(self._items.put)
                self._has_result = True
            except Exception as exc:
                self.error = exc
            finally:
                self._items.put(_DONE)

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()

    def drain(self, phase: str) -> Iterator[tuple[bool, ItemT | str | None]]:
        """Yield ``(is_ping, item)`` until the worker finishes."""
        ping = emit(PingEvent(phase=phase))
        while True:
            try:
                item = self._items.get(timeout=HEARTBEAT_SECONDS)
            except queue.Empty:
                yield True, ping
                continue
            if item is _DONE:
                yield False, None
                return
            yield False, cast(ItemT, item)

    def join(self) -> None:
        if self._thread is None:
            raise RuntimeError("StreamWorker has not been started")
        self._thread.join()

    @property
    def result(self) -> ResultT:
        if self.error is not None:
            raise self.error
        if not self._has_result:
            raise RuntimeError("StreamWorker result read before completion")
        return cast(ResultT, self._result)
