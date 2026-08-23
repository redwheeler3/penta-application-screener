"""Heartbeat behavior for callback-based work streamed through a proxy."""

import json
import time

import app.services.stream_worker as stream_worker
from app.services.stream_worker import StreamWorker


def test_items_pass_through_without_pings_when_never_silent(monkeypatch):
    monkeypatch.setattr(stream_worker, "HEARTBEAT_SECONDS", 0.05)
    worker: StreamWorker[str, str] = StreamWorker()

    def work(put):
        put("alpha")
        put("beta")
        return "done"

    worker.start(work)
    output = list(worker.drain("criteria"))
    worker.join()

    assert output == [(False, "alpha"), (False, "beta"), (False, None)]
    assert worker.result == "done"


def test_silence_injects_ping_before_the_next_item(monkeypatch):
    monkeypatch.setattr(stream_worker, "HEARTBEAT_SECONDS", 0.05)
    worker: StreamWorker[str, None] = StreamWorker()

    def work(put):
        time.sleep(0.17)
        put("late reasoning")

    worker.start(work)
    output = list(worker.drain("criteria"))
    worker.join()

    pings = [item for is_ping, item in output if is_ping]
    real_items = [item for is_ping, item in output if not is_ping]
    assert pings
    assert json.loads(pings[0]) == {"type": "ping", "phase": "criteria"}
    assert pings[0].endswith("\n")
    assert real_items == ["late reasoning", None]
    assert output.index((True, pings[0])) < output.index((False, "late reasoning"))


def test_worker_captures_an_exception_after_streamed_items(monkeypatch):
    monkeypatch.setattr(stream_worker, "HEARTBEAT_SECONDS", 0.05)
    worker: StreamWorker[str, None] = StreamWorker()

    def work(put):
        put("before failure")
        raise ValueError("broken")

    worker.start(work)
    output = list(worker.drain("criteria"))
    worker.join()

    assert output == [(False, "before failure"), (False, None)]
    assert isinstance(worker.error, ValueError)
