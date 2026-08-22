"""Strands implementation of ``AIProvider`` across the supported model routes.

The model catalog owns routing. Callers pass an opaque provider-native model ID;
this module alone decides whether Strands should use Bedrock Runtime, Bedrock
Mantle, OpenAI's Responses API, or Anthropic's Messages API.
"""

from __future__ import annotations

import asyncio
import threading
from typing import TYPE_CHECKING

from app.ai.model_catalog import (
    ModelProvider,
    ModelVendor,
    ReasoningEffort,
    model_spec,
)
from app.ai.provider import AIResult, DeltaSink, SchemaT, Usage

if TYPE_CHECKING:
    from strands.models import Model


OPENAI_PREAMBLE_INSTRUCTION = (
    "Before calling the structured-output function, send a concise Markdown update "
    "explaining what you considered and how you reached the result. This update is shown "
    "live to a human reviewer."
)


class StrandsProvider:
    """Multi-provider Strands adapter, safe to share across the worker pool.

    A Strands model configuration is built once per model id and timeout. Claude's
    cached ``BedrockModel`` owns a shared, thread-safe boto3 connection pool. Direct
    provider SDK clients manage their own connection pools; Mantle mints a fresh
    Bedrock bearer token per request.
    The per-call ``Agent`` is never shared: it accumulates conversation in
    ``agent.messages`` (read back for the narrative), so each call gets a fresh one.
    """

    def __init__(
        self,
        region: str,
        max_pool_connections: int = 50,
        openai_api_key: str = "",
        anthropic_api_key: str = "",
        openai_reasoning_effort: ReasoningEffort | None = None,
        openai_reasoning_efforts: dict[str, ReasoningEffort] | None = None,
    ) -> None:
        self._region = region
        self._openai_api_key = openai_api_key
        self._anthropic_api_key = anthropic_api_key
        self._openai_reasoning_effort = openai_reasoning_effort
        self._openai_reasoning_efforts = openai_reasoning_efforts or {}
        # Size the pool to the worker count so threads don't queue on sockets.
        self._max_pool_connections = max_pool_connections
        # A timeout or reasoning change needs a distinct configured model client.
        self._models: dict[tuple[str, int, str | None], Model] = {}
        self._models_lock = threading.Lock()

    # Default Bedrock read timeout (s). Right for the per-applicant passes (screening,
    # scoring). The heavy pool-wide synthesis passes stream a large reasoned set and blow
    # this, so they pass their own longer read_timeout (discovery: DISCOVERY_READ_TIMEOUT;
    # decomposition: DECOMPOSE_READ_TIMEOUT), keyed separately in the model cache so the
    # tight default stays put for everything else.
    DEFAULT_READ_TIMEOUT = 120

    def _model_for(
        self,
        model_id: str,
        read_timeout: int | None = None,
        reasoning_effort: ReasoningEffort | None = None,
    ) -> Model:
        # Imported lazily so importing this module (and the test suite) does not
        # require the strands/botocore packages or any AWS configuration.
        timeout = read_timeout or self.DEFAULT_READ_TIMEOUT
        effective_effort = None
        spec = model_spec(model_id)
        if spec.supports_reasoning_effort:
            effective_effort = reasoning_effort or self._openai_reasoning_efforts.get(
                model_id, self._openai_reasoning_effort
            )
            if effective_effort is None:
                raise ValueError(
                    f"reasoning_effort is required for OpenAI model {model_id!r}"
                )
        cache_key = (model_id, timeout, effective_effort)
        with self._models_lock:
            model = self._models.get(cache_key)
            if model is None:
                model = self._build_model(model_id, timeout, effective_effort)
                self._models[cache_key] = model
            return model

    def _build_model(
        self, model_id: str, read_timeout: int, reasoning_effort: str | None = None
    ) -> Model:
        spec = model_spec(model_id)
        if spec.vendor is ModelVendor.OPENAI:
            from openai import Timeout
            from strands.models.openai_responses import OpenAIResponsesModel

            client_args = {
                "max_retries": 5,
                "timeout": Timeout(timeout=read_timeout, connect=10),
            }
            route_args: dict[str, object] = {}
            if spec.provider is ModelProvider.BEDROCK:
                route_args["bedrock_mantle_config"] = {"region": self._region}
            else:
                if not self._openai_api_key:
                    raise RuntimeError("OPENAI_API_KEY is required for direct OpenAI models.")
                client_args["api_key"] = self._openai_api_key

            return OpenAIResponsesModel(
                model_id=model_id,
                **route_args,
                client_args=client_args,
                params={
                    "reasoning": {
                        "effort": reasoning_effort,
                        "summary": "auto",
                    }
                },
                # The app supplies full history for each short-lived Agent. Do not ask
                # the upstream service to retain response state between calls.
                stateful=False,
            )

        if spec.provider is ModelProvider.ANTHROPIC:
            if not self._anthropic_api_key:
                raise RuntimeError("ANTHROPIC_API_KEY is required for direct Anthropic models.")
            from strands.models.anthropic import AnthropicModel

            return AnthropicModel(
                model_id=model_id,
                max_tokens=64_000,
                client_args={
                    "api_key": self._anthropic_api_key,
                    "max_retries": 5,
                    "timeout": read_timeout,
                },
            )

        from botocore.config import Config
        from strands.models import BedrockModel

        return BedrockModel(
            model_id=model_id,
            region_name=self._region,
            boto_client_config=Config(
                max_pool_connections=self._max_pool_connections,
                # Adaptive mode backs off on throttling and retries
                # transient 5xx/timeouts — cheap insurance once parallel.
                retries={"max_attempts": 5, "mode": "adaptive"},
                connect_timeout=10,
                read_timeout=read_timeout,
            ),
        )

    def structured_output(
        self,
        *,
        model_id: str,
        schema: type[SchemaT],
        prompt: str,
        system_prompt: str | None = None,
        on_delta: DeltaSink | None = None,
        read_timeout: int | None = None,
        reasoning_effort: ReasoningEffort | None = None,
    ) -> AIResult:
        # One path for every call: drain Strands' (async) streaming API to completion
        # in a private event loop on the calling thread. A spike confirmed this is
        # safe at the worker-pool's ~50-wide fan-out (each thread gets its own loop
        # via asyncio.run). Callers that don't want the deltas simply pass no sink;
        # the only difference is whether on_delta fires. (Why some short/fast calls
        # emit no deltas at all — the model returning one chunk under load — is a
        # known open question parked for observability, not a correctness issue: the
        # structured output + usage always come back.)
        from strands import Agent

        sink = on_delta or (lambda _text: None)
        # callback_handler=None suppresses Strands' default PrintingCallbackHandler,
        # which would otherwise echo streamed reasoning to stdout. The UI is the
        # intended surface for that text (via sink -> the NDJSON stream); the terminal
        # echo is just noise.
        agent = Agent(
            model=self._model_for(model_id, read_timeout, reasoning_effort),
            system_prompt=_system_prompt_for_model(model_id, system_prompt),
            callback_handler=None,
        )

        async def drain() -> object:
            final = None
            async for event in agent.stream_async(prompt, structured_output_model=schema):
                if not isinstance(event, dict):
                    continue
                narrative_delta = _event_narrative_delta(event)
                if narrative_delta:
                    sink(narrative_delta)
                if event.get("result") is not None:
                    final = event["result"]  # the terminal AgentResult
            return final

        result = asyncio.run(drain())
        if result is None:  # no terminal result event — should not happen
            raise RuntimeError("Streaming call produced no result event.")

        usage_data = result.metrics.accumulated_usage
        return AIResult(
            output=result.structured_output,
            usage=Usage(
                input_tokens=usage_data["inputTokens"],
                output_tokens=usage_data["outputTokens"],
            ),
            model_id=model_id,
            narrative=_conversation_narrative(agent.messages),
        )


def _conversation_narrative(messages: object) -> str | None:
    """Join the model's exposed reasoning across the whole conversation.

    Structured output calls a tool, which splits reasoning across several assistant
    turns. ``result.message`` is only the LAST turn, so we walk every assistant
    message and concatenate Claude text or OpenAI reasoning-summary blocks in order.
    """
    if not isinstance(messages, list):
        return None
    parts: list[str] = []
    for message in messages:
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        for block in message.get("content", []):
            text = _content_block_narrative(block)
            if text:
                parts.append(text)
    return "\n\n".join(parts) or None


def _event_narrative_delta(event: dict[str, object]) -> str | None:
    """Return a streamed OpenAI reasoning summary or Claude text delta."""
    reasoning_text = event.get("reasoningText")
    if isinstance(reasoning_text, str) and reasoning_text:
        return reasoning_text
    data = event.get("data")
    return data if isinstance(data, str) and data else None


def _system_prompt_for_model(model_id: str, system_prompt: str | None) -> str | None:
    """Ask OpenAI for a user-visible preamble without changing Claude prompts."""
    if model_spec(model_id).vendor is not ModelVendor.OPENAI:
        return system_prompt
    if not system_prompt:
        return OPENAI_PREAMBLE_INSTRUCTION
    return f"{system_prompt.rstrip()}\n\n{OPENAI_PREAMBLE_INSTRUCTION}"


def _content_block_narrative(block: object) -> str | None:
    """Return narrative text from a Claude or OpenAI Strands content block."""
    if not isinstance(block, dict):
        return None
    text = block.get("text")
    if not isinstance(text, str):
        reasoning_content = block.get("reasoningContent")
        if not isinstance(reasoning_content, dict):
            return None
        reasoning_text = reasoning_content.get("reasoningText")
        if not isinstance(reasoning_text, dict):
            return None
        text = reasoning_text.get("text")
    if not isinstance(text, str):
        return None
    return text.strip() or None
