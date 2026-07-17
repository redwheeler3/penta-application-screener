"""Fan-out discovery resilience (added after a real Bedrock read-timeout on 2026-07-16).

The K parallel discovery workers are redundant by design — decomposition settles however
many reports survive — so a minority failing must NOT abort the run; only ALL K failing
is fatal. These tests drive discover_patterns_fanout with a provider that fails the first
N calls, using a real Session-free path (no DB, no Bedrock)."""

import threading

import pytest

from app.ai.pattern_discovery import discover_patterns_fanout
from app.ai.provider import AIResult, Usage
from app.ai.schemas import PoolDimension, PoolDimensionReport
from app.schemas.settings import AppSettings


def _report(key: str) -> PoolDimensionReport:
    return PoolDimensionReport(dimensions=[
        PoolDimension(key=key, name=key, definition="d",
                      high_end="hi", low_end="lo", why_it_differentiates="v"),
    ])


class _FlakyProvider:
    """structured_output raises for the first ``fail_n`` calls, then succeeds. Thread-safe
    because the fan-out runs the K calls across a pool."""

    def __init__(self, fail_n: int):
        self._fail_n = fail_n
        self._seen = 0
        self._lock = threading.Lock()

    def structured_output(self, *, model_id, schema, prompt, system_prompt=None,
                          on_delta=None, read_timeout=None):
        with self._lock:
            i = self._seen
            self._seen += 1
        if i < self._fail_n:
            raise TimeoutError(f"simulated Bedrock read timeout on call {i}")
        return AIResult(
            output=_report(f"axis_{i}"),
            narrative=None,
            model_id=model_id,
            usage=Usage(input_tokens=10, output_tokens=10),
        )


def _run(provider, k):
    return discover_patterns_fanout(
        provider, applications=[], settings=AppSettings(), k=k, seeds=None,
    )


def test_fanout_tolerates_a_minority_of_failed_workers() -> None:
    # 2 of 5 fail → 3 survivors, run proceeds, failed_count records the loss.
    result = _run(_FlakyProvider(fail_n=2), k=5)

    assert len(result.passes) == 3
    assert result.failed_count == 2
    assert len(result.reports) == 3


def test_fanout_survives_even_a_single_worker() -> None:
    # 4 of 5 fail → 1 survivor is still enough (decomposition settles one report fine).
    result = _run(_FlakyProvider(fail_n=4), k=5)

    assert len(result.passes) == 1
    assert result.failed_count == 4


def test_fanout_aborts_only_when_all_workers_fail() -> None:
    # All 5 fail → nothing to decompose → fatal, and it raises the real underlying cause
    # (not a bare count) so the caller's "Finding criteria failed: <cause>" is accurate.
    with pytest.raises(TimeoutError, match="simulated Bedrock read timeout"):
        _run(_FlakyProvider(fail_n=5), k=5)
