"""Provider-agnostic AI interface.

The rest of the app depends on ``AIProvider`` rather than any vendor SDK. The
real implementation is backed by Strands + Amazon Bedrock; tests use
``MockProvider`` so they run deterministically with no AWS access.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, TypeVar

from pydantic import BaseModel

SchemaT = TypeVar("SchemaT", bound=BaseModel)

# Called with each chunk of the model's reasoning text as it streams, for live
# "thinking" UI during a long single call. Never receives the structured output.
DeltaSink = Callable[[str], None]


@dataclass(frozen=True)
class Usage:
    """Token counts for one model call, used for cost accounting."""

    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class AIResult:
    """A structured-output call result plus the usage needed to price it."""

    output: BaseModel
    usage: Usage
    model_id: str
    # The model's free-text reasoning alongside the structured tool call. None when
    # the provider doesn't surface it. Persisted for the admin view, never parsed.
    narrative: str | None = None


class AIProvider(Protocol):
    """Runs a prompt and returns output validated against a Pydantic schema."""

    def structured_output(
        self,
        *,
        model_id: str,
        schema: type[SchemaT],
        prompt: str,
        system_prompt: str | None = None,
    ) -> AIResult: ...

    def structured_output_streaming(
        self,
        *,
        model_id: str,
        schema: type[SchemaT],
        prompt: str,
        system_prompt: str | None = None,
        on_delta: DeltaSink,
    ) -> AIResult:
        """Like ``structured_output``, but invokes ``on_delta`` with each chunk of the
        model's reasoning text as it streams. Returns the same ``AIResult`` (final
        validated output + usage), so callers get live progress AND the result from
        one call. Used for the long single-call passes (discovery, match) where a
        per-item progress fraction is impossible — the streamed text is the progress.
        """
        ...
