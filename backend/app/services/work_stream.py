"""Own cooperative worker cancellation and source cleanup at the HTTP boundary."""

from collections.abc import Generator
from threading import Event

import anyio
from starlette.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

from app.core.work_cancellation import (
    WorkCancelled,
    cancellation_scope,
    check_cancelled,
)


class WorkStreamingResponse(StreamingResponse):
    """Close a worker-backed stream explicitly on disconnect or consumer failure."""

    def __init__(self, events: Generator[str], *, cancelled: Event | None = None):
        self._events = events
        self._cancelled = cancelled if cancelled is not None else Event()

        def content() -> Generator[str]:
            try:
                while True:
                    # ASGI may resume the generator on a different worker thread.
                    with cancellation_scope(self._cancelled):
                        check_cancelled()
                        line = next(events)
                    yield line
            except (StopIteration, WorkCancelled):
                return
            finally:
                with cancellation_scope(self._cancelled):
                    events.close()

        self._content = content()
        super().__init__(self._content, media_type="application/x-ndjson")

    def _close(self) -> None:
        with cancellation_scope(self._cancelled):
            self._content.close()
            # An unstarted wrapper has no entered finally block.
            self._events.close()

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
            version = tuple(int(part) for part in scope.get("asgi", {}).get("spec_version", "2.0").split("."))
            if scope["type"] == "http" and version >= (2, 4):
                # This transport mode relies on send failures; also observe disconnects
                # while a provider is silent and there is nothing available to send.
                try:
                    async with anyio.create_task_group() as tasks:
                        async def watch_disconnect():
                            await self.listen_for_disconnect(monitored_receive)
                            tasks.cancel_scope.cancel()

                        tasks.start_soon(watch_disconnect)
                        await super().__call__(scope, monitored_receive, monitored_send)
                        tasks.cancel_scope.cancel()
                except BaseExceptionGroup as error:
                    if len(error.exceptions) == 1:
                        raise error.exceptions[0] from None
                    raise
            else:
                await super().__call__(scope, monitored_receive, monitored_send)
        finally:
            self._cancelled.set()
            # Disconnect cancellation must not cancel its own database cleanup.
            with anyio.CancelScope(shield=True):
                await anyio.to_thread.run_sync(self._close)
                await self.body_iterator.aclose()
