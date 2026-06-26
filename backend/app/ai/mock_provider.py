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
    ) -> AIResult:
        with self._lock:
            self.calls.append(MockCall(model_id=model_id, prompt=prompt))
            for substring, result in self.routed.items():
                if substring in prompt:
                    return result
            if not self.results:
                raise AssertionError("MockProvider had no queued result for this call.")
            return self.results.pop(0)

    def structured_output_streaming(
        self,
        *,
        model_id: str,
        schema: type[SchemaT],
        prompt: str,
        system_prompt: str | None = None,
        on_delta,
    ) -> AIResult:
        # Deterministic stand-in: emit a couple of fixed deltas so tests can assert
        # the streaming wiring fires, then return the same routed/queued result the
        # non-streaming path would.
        on_delta("Thinking… ")
        on_delta("considering the pool.")
        return self.structured_output(
            model_id=model_id, schema=schema, prompt=prompt, system_prompt=system_prompt
        )
