"""Deterministic in-memory ``AIProvider`` for tests and offline development.

Returns pre-registered outputs instead of calling Bedrock, and records every
call so tests can assert on caching (no duplicate calls) and cost accounting.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

from pydantic import BaseModel

from app.ai.provider import AIResult, SchemaT, Usage


@dataclass
class MockCall:
    model_id: str
    prompt: str


@dataclass
class MockProvider:
    # Queued results returned in FIFO order, one per structured_output call.
    results: list[AIResult] = field(default_factory=list)
    # Results keyed by a prompt substring, for content-addressed routing. Checked
    # before the FIFO queue. Use this (not queue) when a test needs a specific
    # verdict tied to a specific application, since the screening pass runs calls
    # concurrently and they do not complete in submission order.
    routed: dict[str, AIResult] = field(default_factory=dict)
    calls: list[MockCall] = field(default_factory=list)
    # The real provider is shared across the screening thread pool, so the mock
    # is too. A lock keeps the queue/call-log mutations consistent under workers.
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def _result(
        self,
        output: BaseModel,
        *,
        model_id: str,
        input_tokens: int,
        output_tokens: int,
        narrative: str | None,
    ) -> AIResult:
        return AIResult(
            output=output,
            usage=Usage(input_tokens=input_tokens, output_tokens=output_tokens),
            model_id=model_id,
            narrative=narrative,
        )

    def queue(
        self,
        output: BaseModel,
        *,
        model_id: str = "mock-model",
        input_tokens: int = 100,
        output_tokens: int = 50,
        narrative: str | None = None,
    ) -> None:
        self.results.append(
            self._result(
                output,
                model_id=model_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                narrative=narrative,
            )
        )

    def route(
        self,
        prompt_substring: str,
        output: BaseModel,
        *,
        model_id: str = "mock-model",
        input_tokens: int = 100,
        output_tokens: int = 50,
        narrative: str | None = None,
    ) -> None:
        """Return ``output`` whenever the prompt contains ``prompt_substring``.

        Lets a test bind a verdict to a specific application by a marker in its
        prompt, independent of the order concurrent calls complete in.
        """
        self.routed[prompt_substring] = self._result(
            output,
            model_id=model_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            narrative=narrative,
        )

    def structured_output(
        self,
        *,
        model_id: str,
        schema: type[SchemaT],
        prompt: str,
        system_prompt: str | None = None,
        on_delta=None,
        read_timeout: int | None = None,  # ignored; no real Bedrock call
    ) -> AIResult:
        with self._lock:
            self.calls.append(MockCall(model_id=model_id, prompt=prompt))
            # When a caller wants deltas, emit a couple of deterministic chunks so
            # tests can assert the streaming wiring fires.
            if on_delta is not None:
                on_delta("Thinking… ")
                on_delta("considering the pool.")
            # Content-addressed routing, but schema-aware: a route applies only when
            # its output matches the REQUESTED schema. Lets two passes that share a
            # prompt substring be disambiguated by their output schema, without the test
            # having to order routes carefully.
            for substring, result in self.routed.items():
                if substring in prompt and isinstance(result.output, schema):
                    return result
            if not self.results:
                raise AssertionError("MockProvider had no queued result for this call.")
            return self.results.pop(0)
