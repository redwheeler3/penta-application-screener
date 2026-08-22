"""Provider-selection tests for every supported model route."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.ai.strands_provider import (
    StrandsProvider,
    _conversation_narrative,
    _event_narrative_delta,
    _system_prompt_for_model,
)


def test_claude_uses_bedrock_runtime_model() -> None:
    provider = StrandsProvider(region="us-east-1", max_pool_connections=7)

    with patch("strands.models.BedrockModel") as model_class:
        model = provider._model_for("us.anthropic.claude-haiku-4-5-20251001-v1:0")

    assert model is model_class.return_value
    kwargs = model_class.call_args.kwargs
    assert kwargs["region_name"] == "us-east-1"
    assert kwargs["boto_client_config"].max_pool_connections == 7
    assert kwargs["boto_client_config"].read_timeout == provider.DEFAULT_READ_TIMEOUT


def test_openai_uses_bedrock_mantle_responses_model() -> None:
    provider = StrandsProvider(region="us-east-1", openai_reasoning_effort="low")

    with patch("strands.models.openai_responses.OpenAIResponsesModel") as model_class:
        model = provider._model_for("openai.gpt-5.6-luna", read_timeout=321)

    assert model is model_class.return_value
    kwargs = model_class.call_args.kwargs
    assert kwargs["model_id"] == "openai.gpt-5.6-luna"
    assert kwargs["bedrock_mantle_config"] == {"region": "us-east-1"}
    assert kwargs["client_args"]["max_retries"] == 5
    assert kwargs["client_args"]["timeout"].read == 321
    assert kwargs["params"] == {
        "reasoning": {"effort": "low", "summary": "auto"}
    }
    assert kwargs["stateful"] is False


def test_openai_direct_uses_api_key_without_mantle() -> None:
    provider = StrandsProvider(
        region="us-east-1", openai_api_key="test-openai-key",
        openai_reasoning_effort="low",
    )

    with patch("strands.models.openai_responses.OpenAIResponsesModel") as model_class:
        provider._model_for("gpt-5.6-luna")

    kwargs = model_class.call_args.kwargs
    assert kwargs["model_id"] == "gpt-5.6-luna"
    assert "bedrock_mantle_config" not in kwargs
    assert kwargs["client_args"]["api_key"] == "test-openai-key"


def test_anthropic_direct_uses_api_key() -> None:
    provider = StrandsProvider(
        region="us-east-1", anthropic_api_key="test-anthropic-key"
    )

    with patch("strands.models.anthropic.AnthropicModel") as model_class:
        provider._model_for("claude-sonnet-4-6", read_timeout=321)

    kwargs = model_class.call_args.kwargs
    assert kwargs["model_id"] == "claude-sonnet-4-6"
    assert kwargs["max_tokens"] == 64_000
    assert kwargs["client_args"] == {
        "api_key": "test-anthropic-key",
        "max_retries": 5,
        "timeout": 321,
    }


def test_direct_provider_retry_count_is_configurable() -> None:
    provider = StrandsProvider(
        region="us-east-1",
        anthropic_api_key="test-anthropic-key",
        direct_max_retries=0,
    )

    with patch("strands.models.anthropic.AnthropicModel") as model_class:
        provider._model_for("claude-haiku-4-5-20251001")

    assert model_class.call_args.kwargs["client_args"]["max_retries"] == 0


def test_anthropic_direct_model_is_not_reused_across_event_loops() -> None:
    provider = StrandsProvider(
        region="us-east-1", anthropic_api_key="test-anthropic-key"
    )
    built = MagicMock(side_effect=[MagicMock(), MagicMock()])

    with patch.object(provider, "_build_model", built):
        first = provider._model_for("claude-haiku-4-5-20251001")
        second = provider._model_for("claude-haiku-4-5-20251001")

    assert second is not first
    assert built.call_count == 2


def test_anthropic_direct_client_is_closed_on_the_call_event_loop() -> None:
    provider = StrandsProvider(
        region="us-east-1", anthropic_api_key="test-anthropic-key"
    )
    model = MagicMock()
    model.client.close = AsyncMock()
    output = MagicMock()
    result = SimpleNamespace(
        metrics=SimpleNamespace(
            accumulated_usage={"inputTokens": 12, "outputTokens": 3}
        ),
        structured_output=output,
    )
    agent = MagicMock(messages=[])

    async def stream_async(*_args: object, **_kwargs: object):
        yield {"result": result}

    agent.stream_async = stream_async
    with (
        patch.object(provider, "_model_for", return_value=model),
        patch("strands.Agent", return_value=agent),
    ):
        actual = provider.structured_output(
            model_id="claude-haiku-4-5-20251001",
            schema=dict,
            prompt="Synthetic prompt",
        )

    assert actual.output is output
    model.client.close.assert_awaited_once_with()


@pytest.mark.parametrize("model_id", ["gpt-5.6-luna", "claude-sonnet-4-6"])
def test_direct_provider_requires_its_api_key(model_id: str) -> None:
    provider = StrandsProvider(region="us-east-1", openai_reasoning_effort="low")

    with pytest.raises(RuntimeError, match="API_KEY is required"):
        provider._model_for(model_id)


def test_openai_reasoning_effort_can_be_set_for_bakeoff() -> None:
    provider = StrandsProvider(region="us-east-1", openai_reasoning_effort="low")

    with patch("strands.models.openai_responses.OpenAIResponsesModel") as model_class:
        provider._model_for("openai.gpt-5.6-luna")

    assert model_class.call_args.kwargs["params"] == {
        "reasoning": {"effort": "low", "summary": "auto"}
    }


def test_openai_requires_an_explicit_reasoning_configuration() -> None:
    provider = StrandsProvider(region="us-east-1")

    with pytest.raises(ValueError, match="reasoning_effort is required"):
        provider._model_for("openai.gpt-5.6-luna")


def test_openai_reasoning_effort_can_differ_by_model() -> None:
    provider = StrandsProvider(
        region="us-east-1",
        openai_reasoning_effort="none",
        openai_reasoning_efforts={"gpt-5.6-luna": "low"},
        openai_api_key="test-key",
    )

    with patch("strands.models.openai_responses.OpenAIResponsesModel") as model_class:
        provider._model_for("gpt-5.6-luna")
        provider._model_for("openai.gpt-5.6-terra")

    assert model_class.call_args_list[0].kwargs["params"] == {
        "reasoning": {"effort": "low", "summary": "auto"}
    }
    assert model_class.call_args_list[1].kwargs["params"] == {
        "reasoning": {"effort": "none", "summary": "auto"}
    }


def test_models_are_cached_by_model_timeout_and_reasoning() -> None:
    provider = StrandsProvider(region="us-east-1", openai_reasoning_effort="low")
    built = MagicMock(side_effect=[MagicMock(), MagicMock(), MagicMock(), MagicMock()])

    with patch.object(provider, "_build_model", built):
        first = provider._model_for("openai.gpt-5.6-luna")
        same = provider._model_for("openai.gpt-5.6-luna")
        longer = provider._model_for("openai.gpt-5.6-luna", read_timeout=300)
        other = provider._model_for("openai.gpt-5.6-terra")
        medium = provider._model_for("openai.gpt-5.6-luna", reasoning_effort="medium")

    assert same is first
    assert longer is not first
    assert other is not first
    assert medium is not first
    assert built.call_count == 4


def test_streamed_narrative_supports_openai_and_claude_events() -> None:
    assert _event_narrative_delta({"reasoningText": "Considering evidence"}) == (
        "Considering evidence"
    )
    assert _event_narrative_delta({"data": "Comparing applicants"}) == (
        "Comparing applicants"
    )
    assert _event_narrative_delta(
        {"reasoningText": "Summary", "data": "Duplicate"}
    ) == "Summary"
    assert _event_narrative_delta({"reasoningText": "", "data": ""}) is None


def test_conversation_narrative_supports_openai_and_claude_blocks() -> None:
    messages = [
        {"role": "user", "content": [{"text": "Ignore user text"}]},
        {
            "role": "assistant",
            "content": [
                {"text": " Claude narrative "},
                {
                    "reasoningContent": {
                        "reasoningText": {"text": " OpenAI summary "}
                    }
                },
                {"toolUse": {"name": "structured_output"}},
            ],
        },
    ]

    assert _conversation_narrative(messages) == (
        "Claude narrative\n\nOpenAI summary"
    )


def test_openai_requests_a_user_visible_preamble() -> None:
    prompt = _system_prompt_for_model("gpt-5.6-terra", "Base instructions\n")

    assert prompt is not None
    assert prompt.startswith("Base instructions\n\n")
    assert "Before calling the structured-output function" in prompt


def test_claude_system_prompt_is_unchanged() -> None:
    prompt = "Base instructions\n"

    assert _system_prompt_for_model("us.anthropic.claude-sonnet-4-6", prompt) == prompt
