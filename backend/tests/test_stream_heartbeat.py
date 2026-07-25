"""Heartbeat cadence for the opaque rank passes (M17, ADR 0012).

The criteria and consolidation passes can go >60s without streaming a token; a hosting
proxy that closes an idle connection (Fly's 60s limit) would sever the stream. The drain
helper injects a keepalive during any silence longer than HEARTBEAT_SECONDS. These tests
pin the three behaviors that make that safe: items pass through untouched, a silent gap
yields a ping, and the None completion sentinel still terminates the drain.

HEARTBEAT_SECONDS is monkeypatched small so the tests run fast and deterministically —
we assert the *mechanism* (silence → ping), not the wall-clock constant.
"""

import json
import queue
import threading
import time

import app.api.ranking.run as run
from app.api.ranking.run import _drain_with_heartbeat, _Stage


def _drain_kinds(q: queue.Queue) -> list:
    """Run the drain to completion, returning each yielded (is_ping, item)."""
    return list(_drain_with_heartbeat(q, "criteria"))


def test_items_pass_through_without_pings_when_never_silent(monkeypatch):
    # A queue already full (no silence) drains straight through: every real item is
    # surfaced as (False, item), the None sentinel included, and no ping is injected.
    monkeypatch.setattr(run, "HEARTBEAT_SECONDS", 0.05)
    q: queue.Queue = queue.Queue()
    q.put("alpha")
    q.put(_Stage("settling"))
    q.put("beta")
    q.put(None)

    out = _drain_kinds(q)

    assert all(not is_ping for is_ping, _ in out), "no silence → no pings"
    assert out[0] == (False, "alpha")
    assert isinstance(out[1][1], _Stage)
    assert out[2] == (False, "beta")
    assert out[-1] == (False, None), "None sentinel is surfaced so the caller can break"


def test_silence_injects_a_ping_then_the_real_item(monkeypatch):
    # A producer that stays silent past the heartbeat interval, then emits one item and
    # completes. The drain must surface at least one ping (is_ping=True) BEFORE the item,
    # and the ping must be a valid pre-serialized NDJSON ping line for the phase.
    monkeypatch.setattr(run, "HEARTBEAT_SECONDS", 0.05)
    q: queue.Queue = queue.Queue()

    def slow_producer() -> None:
        time.sleep(0.17)  # ~3 heartbeat intervals of silence
        q.put("late reasoning")
        q.put(None)

    threading.Thread(target=slow_producer, daemon=True).start()
    out = _drain_kinds(q)

    pings = [item for is_ping, item in out if is_ping]
    reals = [item for is_ping, item in out if not is_ping]
    assert len(pings) >= 1, "a >HEARTBEAT_SECONDS silence must emit at least one ping"
    # Ping is a serialized NDJSON line the caller re-yields verbatim.
    parsed = json.loads(pings[0])
    assert parsed == {"type": "ping", "phase": "criteria"}
    assert pings[0].endswith("\n")
    # The real item and the completion sentinel still come through, in order, after the pings.
    assert reals == ["late reasoning", None]
    # The first ping precedes the real item in the overall stream.
    assert out.index((True, pings[0])) < out.index((False, "late reasoning"))


def test_none_sentinel_terminates_even_if_more_is_queued(monkeypatch):
    # The drain must stop at the first None (the completion signal), not keep reading —
    # anything queued after None is the caller's problem, never surfaced here.
    monkeypatch.setattr(run, "HEARTBEAT_SECONDS", 0.05)
    q: queue.Queue = queue.Queue()
    q.put("only")
    q.put(None)
    q.put("SHOULD NOT APPEAR")

    out = _drain_kinds(q)

    assert out == [(False, "only"), (False, None)]
