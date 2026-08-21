"""Strands + Amazon Bedrock implementation of ``AIProvider``.

Claude model IDs here must be inference profile IDs (e.g.
``us.anthropic.claude-haiku-4-5-20251001-v1:0``). OpenAI model IDs use
Bedrock's Mantle names (e.g. ``openai.gpt-5.6-luna``). Only model invocation is
performed — no AWS resources are created, modified, or deleted.
"""

from __future__ import annotations

import asyncio
import threading
from typing import TYPE_CHECKING

from app.ai.provider import AIResult, DeltaSink, SchemaT, Usage
from app.schemas.settings import ReasoningEffort

if TYPE_CHECKING:
    from strands.models import Model


OPENAI_MODEL_PREFIX = "openai."
class StrandsProvider:
    """Bedrock-backed provider, safe to share across the screening thread pool.

    A Strands model configuration is built once per model id and timeout. Claude's
    cached ``BedrockModel`` owns a shared, thread-safe boto3 connection pool; the
    OpenAI Responses adapter mints a fresh Bedrock bearer token and client per call.
    The per-call ``Agent`` is never shared: it accumulates conversation in
    ``agent.messages`` (read back for the narrative), so each call gets a fresh one.
    """

    def __init__(
        self,
        region: str,
        max_pool_connections: int = 50,
        openai_reasoning_effort: ReasoningEffort | None = None,
        openai_reasoning_efforts: dict[str, ReasoningEffort] | None = None,
    ) -> None:
        self._region = region
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
        if model_id.startswith(OPENAI_MODEL_PREFIX):
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
        if model_id.startswith(OPENAI_MODEL_PREFIX):
            from openai import Timeout
            from strands.models.openai_responses import OpenAIResponsesModel

            return OpenAIResponsesModel(
                model_id=model_id,
                bedrock_mantle_config={"region": self._region},
                client_args={
                    "max_retries": 5,
                    "timeout": Timeout(
                        timeout=read_timeout,
                        connect=10,
                    ),
                },
                params={
                    "reasoning": {
                        "effort": reasoning_effort
                    }
                },
                # The app supplies full history for each short-lived Agent. Do not ask
                # the upstream service to retain response state between calls.
                stateful=False,
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
            system_prompt=system_prompt,
            callback_handler=None,
        )

        async def drain() -> object:
            final = None
            async for event in agent.stream_async(prompt, structured_output_model=schema):
                if not isinstance(event, dict):
                    continue
                data = event.get("data")
                if isinstance(data, str) and data:
                    sink(data)  # a chunk of reasoning text
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
    """Join the model's reasoning text across the whole conversation.

    Structured output calls a tool, which splits reasoning across several assistant
    turns. ``result.message`` is only the LAST turn, so we walk every assistant
    message and concatenate its text blocks (dropping toolUse/toolResult), in order.
    """
    if not isinstance(messages, list):
        return None
    parts: list[str] = []
    for message in messages:
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        for block in message.get("content", []):
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                text = block["text"].strip()
                if text:
                    parts.append(text)
    return "\n\n".join(parts) or None
