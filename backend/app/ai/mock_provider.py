"""Deterministic in-memory ``AIProvider`` for tests and offline development.

Returns pre-registered outputs instead of calling Bedrock, and records every
call so tests can assert on caching (no duplicate calls) and cost accounting.
"""

from __future__ import annotations

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
    calls: list[MockCall] = field(default_factory=list)

    def queue(
        self,
        output: BaseModel,
        *,
        model_id: str = "mock-model",
        input_tokens: int = 100,
        output_tokens: int = 50,
    ) -> None:
        self.results.append(
            AIResult(
                output=output,
                usage=Usage(input_tokens=input_tokens, output_tokens=output_tokens),
                model_id=model_id,
            )
        )

    def structured_output(
        self,
        *,
        model_id: str,
        schema: type[SchemaT],
        prompt: str,
        system_prompt: str | None = None,
    ) -> AIResult:
        self.calls.append(MockCall(model_id=model_id, prompt=prompt))
        if not self.results:
            raise AssertionError("MockProvider had no queued result for this call.")
        return self.results.pop(0)
