"""Strands + Amazon Bedrock implementation of ``AIProvider``.

Bedrock model IDs here must be inference profile IDs (e.g.
``us.anthropic.claude-haiku-4-5-20251001-v1:0``); the bare on-demand IDs are
rejected by Bedrock for these models. Only model invocation is performed — no
AWS resources are created, modified, or deleted.
"""

from __future__ import annotations

from app.ai.provider import AIResult, SchemaT, Usage


class StrandsProvider:
    def __init__(self, region: str) -> None:
        self._region = region

    def structured_output(
        self,
        *,
        model_id: str,
        schema: type[SchemaT],
        prompt: str,
        system_prompt: str | None = None,
    ) -> AIResult:
        # Imported lazily so importing this module (and the test suite) does not
        # require the strands package or any AWS configuration to be present.
        from strands import Agent
        from strands.models import BedrockModel

        agent = Agent(
            model=BedrockModel(model_id=model_id, region_name=self._region),
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
