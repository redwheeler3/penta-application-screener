"""Strands + Amazon Bedrock implementation of ``AIProvider``.

Bedrock model IDs here must be inference profile IDs (e.g.
``us.anthropic.claude-haiku-4-5-20251001-v1:0``); the bare on-demand IDs are
rejected by Bedrock for these models. Only model invocation is performed — no
AWS resources are created, modified, or deleted.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from app.ai.provider import AIResult, SchemaT, Usage

if TYPE_CHECKING:
    from strands.models import BedrockModel


class StrandsProvider:
    """Bedrock-backed provider, safe to share across the screening thread pool.

    The boto3 Bedrock client (which owns the HTTP connection pool) is built once
    per model id and reused: it is stateless and thread-safe, so one shared
    client lets every worker draw from a single connection pool. The per-call
    ``Agent`` is *not* shared — it accumulates the conversation in
    ``agent.messages`` (read back for the narrative), so each call gets a fresh,
    cheap one.
    """

    def __init__(self, region: str, max_pool_connections: int = 50) -> None:
        self._region = region
        # Size the connection pool to the worker count so threads don't queue on
        # sockets; one knob (worker count) drives the other (pool size).
        self._max_pool_connections = max_pool_connections
        self._models: dict[str, BedrockModel] = {}
        self._models_lock = threading.Lock()

    def _model_for(self, model_id: str) -> BedrockModel:
        # Imported lazily so importing this module (and the test suite) does not
        # require the strands/botocore packages or any AWS configuration.
        from botocore.config import Config
        from strands.models import BedrockModel

        with self._models_lock:
            model = self._models.get(model_id)
            if model is None:
                model = BedrockModel(
                    model_id=model_id,
                    region_name=self._region,
                    boto_client_config=Config(
                        max_pool_connections=self._max_pool_connections,
                        # Adaptive mode backs off on throttling and retries
                        # transient 5xx/timeouts — cheap insurance once parallel.
                        retries={"max_attempts": 5, "mode": "adaptive"},
                        connect_timeout=10,
                        read_timeout=120,
                    ),
                )
                self._models[model_id] = model
            return model

    def structured_output(
        self,
        *,
        model_id: str,
        schema: type[SchemaT],
        prompt: str,
        system_prompt: str | None = None,
    ) -> AIResult:
        # Imported lazily for the same reason as the model above.
        from strands import Agent

        agent = Agent(
            model=self._model_for(model_id),
            system_prompt=system_prompt,
        )
        result = agent(prompt, structured_output_model=schema)

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

    When the model produces structured output it calls a tool, which splits its
    reasoning across several assistant turns: a short preamble in one message, the
    detailed analysis in others, plus tool-use/tool-result messages in between.
    ``result.message`` is only the LAST turn, so it captures just the preamble for
    flagged applications. We therefore walk every assistant message and concatenate
    its text blocks (dropping toolUse/toolResult blocks), preserving order.
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
